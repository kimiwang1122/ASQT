"""IS grid search → fixed OOS gate. Lab may overwrite paper parameter_set_id with a warning."""

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
        # Prefer longer mom / smaller k for lower turnover when reviewing OOS.
        for mw, ml, k in itertools.product((20, 40), (20, 40, 60), (2, 3))
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
    "stock_short_reversal_topk": [
        {
            "lookback": lb,
            "top_k": k,
            "max_weight": 0.10,
            "gross_limit": gross,
            "rebalance_every_n": reb,
        }
        # Longer lookback / smaller k / optional N-day rebalance to cut fees.
        for lb, k, reb, gross in itertools.product(
            (10, 15, 20),
            (2, 3),
            (1, 5),
            (0.95,),
        )
    ]
    + [
        {
            "lookback": lb,
            "top_k": k,
            "max_weight": 0.10,
            "gross_limit": 0.70,
            "rebalance_every_n": 5,
        }
        for lb, k in itertools.product((10, 15), (2, 3))
    ]
    + [
        # Baseline + rebalance variants of the toxic papered set.
        {
            "lookback": 5,
            "top_k": 5,
            "max_weight": 0.10,
            "gross_limit": 0.95,
            "rebalance_every_n": reb,
        }
        for reb in (1, 5)
    ],
    "stock_momentum_volume_confirm": [
        {
            "lookback": lb,
            "vol_z_window": vz,
            "min_volume_z": mz,
            "top_k": k,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        }
        for lb, vz, mz, k in itertools.product(
            (20, 40, 60),
            (20,),
            (0.0, 0.5),
            (3, 5),
        )
    ],
    "stock_momentum_skip_month": [
        {
            "lookback": lb,
            "skip": sk,
            "top_k": k,
            "max_weight": 0.10,
            "gross_limit": 0.95,
        }
        for lb, sk, k in itertools.product(
            (126, 189, 252),
            (10, 21),
            (3, 5),
        )
    ],
    "stock_2560": [
        {
            "ma_fast": 5,
            "ma_slow": slow,
            "vol_fast": 5,
            "vol_slow": vol_slow,
            "pullback_band": band,
            "top_k": k,
            "max_weight": max_w,
            "gross_limit": 0.95,
        }
        for slow, vol_slow, band, k, max_w in itertools.product(
            (20, 25, 30),
            (60,),
            (0.02, 0.03),
            (3, 5),
            (0.10,),
        )
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
    if strategy_id == "stock_short_reversal_topk":
        parts = [
            "stock_short_reversal_topk",
            f"k{int(params['top_k'])}",
            f"l{int(params['lookback'])}",
        ]
        gross = float(params.get("gross_limit", 0.95))
        if abs(gross - 0.95) > 1e-9:
            parts.append(f"g{int(round(gross * 100))}")
        reb = int(params.get("rebalance_every_n") or 1)
        if reb > 1:
            parts.append(f"r{reb}")
        return ".".join(parts)
    if strategy_id == "stock_momentum_volume_confirm":
        return (
            f"stock_momentum_volume_confirm.k{int(params['top_k'])}"
            f".l{int(params['lookback'])}.vz{int(params['vol_z_window'])}"
        )
    if strategy_id == "stock_momentum_skip_month":
        return (
            f"stock_momentum_skip_month.k{int(params['top_k'])}"
            f".l{int(params['lookback'])}.s{int(params['skip'])}"
        )
    if strategy_id == "stock_2560":
        band = float(params.get("pullback_band", 0.02))
        band_tag = f"b{int(round(band * 1000))}"
        parts = [
            f"stock_2560.k{int(params['top_k'])}",
            f"f{int(params['ma_fast'])}.s{int(params['ma_slow'])}",
            f"vf{int(params['vol_fast'])}.vs{int(params['vol_slow'])}",
            band_tag,
        ]
        max_w = float(params.get("max_weight", 0.10))
        if abs(max_w - 0.10) > 1e-9:
            parts.append(f"w{int(round(max_w * 100))}")
        return ".".join(parts)
    parts = [strategy_id] + [
        f"{key}{params[key]}"
        for key in sorted(params)
        if key not in {"max_weight", "gross_limit", "rebalance_every_n"}
    ]
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
    if strategy_id == "stock_2560":
        return _simulate_path_2560(
            params=params, rows=rows, limits=limits, dates=dates, is_end=is_end
        )
    grouped = market_by_symbol(rows)
    halted = suspended_keys(limits)
    by_date_symbol = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
    nav = 1.0
    is_points: list[dict[str, Any]] = []
    oos_points: list[dict[str, Any]] = []
    last_weights: dict[str, float] = {}
    turnover = 0.0
    prev_weights: dict[str, float] = {}
    rebalance_every_n = max(1, int(params.get("rebalance_every_n") or 1))
    for index, signal_date in enumerate(dates[:-1]):
        fill_date = dates[index + 1]
        if index % rebalance_every_n == 0 or not last_weights:
            weights = weights_for(
                strategy_id,
                rows,
                signal_date,
                limits=limits,
                params=params,
                market_by_symbol=grouped,
                suspended=halted,
            )
        else:
            weights = dict(last_weights)
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


def _simulate_path_2560(
    *,
    params: dict[str, Any],
    rows: list[dict[str, Any]],
    limits: list[dict[str, Any]],
    dates: list[str],
    is_end: str,
) -> dict[str, Any]:
    """Sticky 2560 path with one timeline pass per symbol (fast grid)."""
    from asqt.factors import rule_2560_timeline
    from asqt.selectors import clip_weights

    grouped = market_by_symbol(rows)
    halted = suspended_keys(limits)
    by_date_symbol = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
    top_k = int(params["top_k"])
    max_weight = float(params["max_weight"])
    gross_limit = float(params["gross_limit"])
    tl_kw = {
        "ma_fast": int(params["ma_fast"]),
        "ma_slow": int(params["ma_slow"]),
        "vol_fast": int(params["vol_fast"]),
        "vol_slow": int(params["vol_slow"]),
        "pullback_band": float(params["pullback_band"]),
    }
    timelines: dict[str, list[tuple[str, float] | None]] = {}
    asof_index: dict[str, dict[str, int]] = {}
    for symbol, series in grouped.items():
        timelines[symbol] = rule_2560_timeline(series, **tl_kw)
        asof_index[symbol] = {str(row["trade_date"]): i for i, row in enumerate(series)}

    def weights_on(signal_date: str, held: list[str]) -> dict[str, float]:
        states: dict[str, tuple[str, float]] = {}
        for symbol, index_map in asof_index.items():
            if (symbol, signal_date) in halted:
                continue
            idx = index_map.get(signal_date)
            if idx is None:
                continue
            state = timelines[symbol][idx]
            if state is not None:
                states[symbol] = state
        keep: list[str] = []
        for symbol in held:
            if symbol in states and symbol not in keep:
                keep.append(symbol)
            if len(keep) >= top_k:
                break
        slots = top_k - len(keep)
        entries = sorted(
            (
                (score, symbol)
                for symbol, (phase, score) in states.items()
                if phase == "entry" and symbol not in keep
            ),
            reverse=True,
        )
        if not keep and slots == top_k:
            ranked = sorted(((score, symbol) for symbol, (_p, score) in states.items()), reverse=True)
            picked = [symbol for _score, symbol in ranked[:top_k]]
        else:
            picked = keep + [symbol for _score, symbol in entries[:slots]]
        if not picked:
            return {}
        weight = 1.0 / len(picked)
        return clip_weights({symbol: weight for symbol in picked}, max_weight, gross_limit)

    nav = 1.0
    is_points: list[dict[str, Any]] = []
    oos_points: list[dict[str, Any]] = []
    last_weights: dict[str, float] = {}
    turnover = 0.0
    prev_weights: dict[str, float] = {}
    for index, signal_date in enumerate(dates[:-1]):
        fill_date = dates[index + 1]
        weights = weights_on(signal_date, list(last_weights))
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
                "blocked_paper_id": False,
                "paper_id_warning": candidate_id in frozen or (candidate_id == pinned and pinned in frozen),
                **path,
            }
        )

    ranked = sorted(results, key=_rank_key, reverse=True)
    winner = ranked[0] if ranked else None

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
            "paper_id_warning": bool(winner.get("paper_id_warning")),
            "note": (
                "Lab may pin suggested_parameter_set_id via pin_strategy_params; "
                "overwrite writes a new parameter_set_id and keep experiment reports."
                if winner.get("paper_id_warning")
                else "Copy suggested_parameter_set_id into STRATEGY_SPECS after review, "
                "or pin via lab runner (reports keep history)."
            ),
        },
        "grid": [
            {
                "params": row["params"],
                "suggested_parameter_set_id": row["suggested_parameter_set_id"],
                "paper_id_warning": bool(row.get("paper_id_warning")),
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
    from asqt.reporting import write_run_tree

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{report['strategy_id']}_{stamp}"
    return write_run_tree(
        "tune",
        run_id,
        report,
        settings=settings,
        strategy_id=str(report.get("strategy_id") or ""),
    )
