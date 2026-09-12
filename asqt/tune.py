"""IS grid search → fixed OOS gate. Does not mutate paper parameter_set_id."""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import initialize_database, query_all
from asqt.pipeline import check_market_daily
from asqt.research_engine import _nav_metrics, data_version_for
from asqt.storage import read_market_daily
from asqt.strategies import (
    STRATEGY_SPECS,
    adj_close,
    market_by_symbol,
    suspended_keys,
    weights_for,
)

# Default grids kept small (≤24 cells).
DEFAULT_GRIDS: dict[str, list[dict[str, Any]]] = {
    "stock_lowvol_momentum": [
        {"lookback": lb, "vol_window": vw, "top_k": k, "max_weight": 0.10, "gross_limit": 0.95}
        for lb, vw, k in itertools.product((10, 20, 40), (20,), (3, 5))
    ],
    "etf_ma_momentum_filter": [
        {
            "ma_window": mw,
            "mom_lookback": ml,
            "top_k": k,
            "max_weight": 0.20,
            "gross_limit": 0.95,
        }
        for mw, ml, k in itertools.product((20,), (20, 40), (2, 3))
    ],
    "stock_momentum_topk": [
        {"lookback": lb, "top_k": k, "max_weight": 0.10, "gross_limit": 0.95}
        for lb, k in itertools.product((10, 20, 40), (3, 5))
    ],
    "etf_momentum_topk": [
        {"lookback": lb, "top_k": k, "max_weight": 0.20, "gross_limit": 0.95}
        for lb, k in itertools.product((20, 40), (2, 3))
    ],
    "etf_ma_rotate": [
        {"window": w, "max_weight": 0.20, "gross_limit": 0.95} for w in (10, 20, 40, 60)
    ],
}

MAX_GRID = 24


def in_sample_end(dates: list[str]) -> str:
    if len(dates) < 4:
        raise ValueError("need at least 4 trade dates to isolate an out-of-sample window")
    return dates[int(len(dates) * 0.7)]


def papered_parameter_set_ids(settings: Settings | None = None) -> set[str]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    rows = query_all(
        """
        SELECT parameter_set_id FROM strategy_version
        WHERE status IN ('paper', 'paused', 'retired')
        """,
        settings=settings,
    )
    return {str(row["parameter_set_id"]) for row in rows if row.get("parameter_set_id")}


def suggest_parameter_set_id(strategy_id: str, params: dict[str, Any]) -> str:
    """Deterministic candidate id from strategy + key params (not applied automatically)."""
    if strategy_id == "stock_lowvol_momentum":
        return (
            f"stock_lowvol_momentum.k{int(params['top_k'])}"
            f".l{int(params['lookback'])}.v{int(params['vol_window'])}"
        )
    if strategy_id == "etf_ma_momentum_filter":
        return (
            f"etf_ma_momentum_filter.k{int(params['top_k'])}"
            f".m{int(params['ma_window'])}.l{int(params['mom_lookback'])}"
        )
    if strategy_id == "stock_momentum_topk":
        return f"stock_momentum_topk.k{int(params['top_k'])}.l{int(params['lookback'])}"
    if strategy_id == "etf_momentum_topk":
        return f"etf_momentum_topk.k{int(params['top_k'])}.l{int(params['lookback'])}"
    if strategy_id == "etf_ma_rotate":
        return f"etf_ma_rotate.w{int(params['window'])}"
    parts = [strategy_id] + [f"{key}{params[key]}" for key in sorted(params) if key not in {"max_weight", "gross_limit"}]
    return ".".join(str(part) for part in parts)


def simulate_path(
    strategy_id: str,
    *,
    params: dict[str, Any],
    rows: list[dict[str, Any]],
    limits: list[dict[str, Any]],
    dates: list[str],
    is_end: str,
) -> dict[str, Any]:
    """Replay T+1 weights path with override params; no DB writes."""
    grouped = market_by_symbol(rows)
    halted = suspended_keys(limits)
    by_date_symbol = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
    nav = 1.0
    is_points: list[dict[str, Any]] = []
    oos_points: list[dict[str, Any]] = []
    last_weights: dict[str, float] = {}
    turnover = 0.0
    prev_weights: dict[str, float] = {}
    for index, signal_date in enumerate(dates[:-1]):
        fill_date = dates[index + 1]
        weights = weights_for(
            strategy_id,
            rows,
            signal_date,
            limits=limits,
            params=params,
            market_by_symbol=grouped,
            suspended=halted,
        )
        last_weights = weights
        symbols = set(prev_weights) | set(weights)
        turnover += 0.5 * sum(abs(weights.get(sym, 0.0) - prev_weights.get(sym, 0.0)) for sym in symbols)
        prev_weights = weights
        period_return = 0.0
        for symbol, weight in weights.items():
            left = by_date_symbol.get((signal_date, symbol))
            right = by_date_symbol.get((fill_date, symbol))
            if not left or not right:
                continue
            start_px = adj_close(left)
            if start_px <= 0:
                continue
            period_return += weight * (adj_close(right) / start_px - 1.0)
        nav = round(nav * (1.0 + period_return), 12)
        point = {"trade_date": fill_date, "nav": nav, "gross": round(sum(weights.values()), 10)}
        if fill_date <= is_end:
            is_points.append(point)
        else:
            oos_points.append(point)
    is_metrics = _nav_metrics(is_points, start_nav=1.0)
    oos_start = float(is_points[-1]["nav"]) if is_points else 1.0
    oos_metrics = _nav_metrics(oos_points, start_nav=oos_start)
    sessions = max(1, len(dates) - 1)
    return {
        "nav": round(nav, 10),
        "metrics": {"is": is_metrics, "oos": oos_metrics},
        "last_weights": last_weights,
        "avg_turnover": round(turnover / sessions, 10),
        "in_sample_end": is_end,
    }


def _rank_key(row: dict[str, Any]) -> tuple:
    is_m = (row.get("metrics") or {}).get("is") or {}
    # Prefer higher IS return, then shallower drawdown, then lower turnover.
    return (
        float(is_m.get("total_return") or -1e9),
        -abs(float(is_m.get("max_drawdown") or 0.0)),
        -float(row.get("avg_turnover") or 0.0),
    )


def run_tune(
    strategy_id: str,
    *,
    grid: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    metric: str = "is_total_return",
) -> dict[str, Any]:
    """Grid on IS, evaluate winner on OOS; write experiment JSON. Never rewrites paper IDs."""
    del metric  # reserved; ranking uses IS total_return + dd + turnover
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    quality = check_market_daily(settings=settings)
    if not quality.get("trade_allowed", False):
        raise ValueError("quality block: refuse tune while trade_allowed is false")

    cells = list(grid) if grid is not None else list(DEFAULT_GRIDS.get(strategy_id) or [])
    if not cells:
        raise ValueError(f"no default grid for {strategy_id}; pass --grid JSON")
    if len(cells) > MAX_GRID:
        raise ValueError(f"grid size {len(cells)} exceeds MAX_GRID={MAX_GRID}")

    frozen = papered_parameter_set_ids(settings)
    pinned = STRATEGY_SPECS[strategy_id]["parameter_set_id"]
    rows = read_market_daily(settings=settings)
    dates = sorted({str(row["trade_date"]) for row in rows})
    is_end = in_sample_end(dates)
    limits = query_all("SELECT * FROM limit_suspension", settings=settings)
    data_version = data_version_for(rows)

    results: list[dict[str, Any]] = []
    for params in cells:
        merged = dict(STRATEGY_SPECS[strategy_id]["params"])
        merged.update(params)
        path = simulate_path(
            strategy_id,
            params=merged,
            rows=rows,
            limits=limits,
            dates=dates,
            is_end=is_end,
        )
        candidate_id = suggest_parameter_set_id(strategy_id, merged)
        results.append(
            {
                "params": merged,
                "suggested_parameter_set_id": candidate_id,
                "blocked_paper_id": candidate_id in frozen or (candidate_id == pinned and pinned in frozen),
                **path,
            }
        )

    ranked = sorted(results, key=_rank_key, reverse=True)
    winner = ranked[0] if ranked else None
    if winner and winner.get("blocked_paper_id") and winner["suggested_parameter_set_id"] == pinned:
        # Prefer next non-identical suggestion when top hits frozen pin with same id.
        for row in ranked[1:]:
            if row["suggested_parameter_set_id"] != pinned:
                winner = row
                break

    report = {
        "ok": bool(winner),
        "run_id": str(uuid4()),
        "strategy_id": strategy_id,
        "kind": "tune_grid",
        "metric": "is_total_return",
        "data_version": data_version,
        "in_sample_end": is_end,
        "grid_size": len(cells),
        "pinned_parameter_set_id": pinned,
        "papered_parameter_set_ids": sorted(frozen),
        "winner": None
        if not winner
        else {
            "params": winner["params"],
            "suggested_parameter_set_id": winner["suggested_parameter_set_id"],
            "metrics": winner["metrics"],
            "nav": winner["nav"],
            "avg_turnover": winner["avg_turnover"],
            "note": (
                "Copy suggested_parameter_set_id into STRATEGY_SPECS after review; "
                "tune never mutates paper parameter sets."
            ),
        },
        "grid": [
            {
                "params": row["params"],
                "suggested_parameter_set_id": row["suggested_parameter_set_id"],
                "metrics": row["metrics"],
                "nav": row["nav"],
                "avg_turnover": row["avg_turnover"],
            }
            for row in ranked
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _write_tune_report(report, settings=settings)
    report["experiment_path"] = str(path)
    return report


def _write_tune_report(report: dict[str, Any], *, settings: Settings) -> Path:
    folder = settings.experiment_dir
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"tune_{report['strategy_id']}_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = folder / f"latest-tune-{report['strategy_id']}.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path
