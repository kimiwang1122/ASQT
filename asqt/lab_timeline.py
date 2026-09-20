"""Lab timeline payload: strategy nav + benchmark + regime bands for the trade chart."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import initialize_database, query_all
from asqt.lab_insight import benchmark_series, build_insight, label_regimes
from asqt.paper import account_id_for, paper_board
from asqt.reporting import experiment_root
from asqt.storage import read_market_daily
from asqt.strategies import STRATEGY_SPECS

LAB_GRID_PREFIX = "etf_ma_momentum_grid_"
LAB_GRID_STRATEGY = "etf_ma_momentum_filter"


def _rel_experiment_path(path: str | Path, *, settings: Settings) -> str:
    raw = Path(path)
    try:
        return str(raw.resolve().relative_to(experiment_root(settings).resolve()))
    except Exception:
        return raw.name


def latest_lab_grid_path(*, settings: Settings | None = None) -> Path | None:
    """Prefer latest pointer, else newest etf_ma_momentum_grid_*/summary.json by mtime."""
    settings = ensure_runtime_dirs(settings or get_settings())
    pointer = experiment_root(settings) / "latest" / "paper" / "etf_ma_momentum_grid.json"
    if pointer.exists():
        return pointer
    paper_root = experiment_root(settings) / "paper"
    if not paper_root.exists():
        return None
    candidates = sorted(
        paper_root.glob(f"{LAB_GRID_PREFIX}*/summary.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_latest_lab_grid(*, settings: Settings | None = None) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    path = latest_lab_grid_path(settings=settings)
    if not path:
        return {"ok": False, "strategy_id": LAB_GRID_STRATEGY, "rows": [], "reason": "no_lab_grid"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "strategy_id": LAB_GRID_STRATEGY, "rows": [], "reason": str(exc)}
    rows = []
    for row in payload.get("rows") or []:
        item = dict(row)
        if item.get("experiment_path"):
            item["experiment_path"] = _rel_experiment_path(item["experiment_path"], settings=settings)
        rs = item.get("regime_stats") or {}
        item["regime_return_up"] = (rs.get("trend_up") or {}).get("total_return")
        item["regime_return_range"] = (rs.get("range") or {}).get("total_return")
        item["regime_return_down"] = (rs.get("trend_down") or {}).get("total_return")
        rows.append(item)
    rows_sorted = sorted(rows, key=lambda r: float(r.get("total_return") or -1e9), reverse=True)
    return {
        "ok": True,
        "strategy_id": LAB_GRID_STRATEGY,
        "batch_id": payload.get("batch_id"),
        "days": payload.get("days"),
        "source": str(path),
        "rows": rows_sorted,
        "winner": rows_sorted[0] if rows_sorted else None,
    }


def write_lab_grid_latest(summary: dict[str, Any], *, settings: Settings | None = None) -> Path:
    """Refresh latest/paper/etf_ma_momentum_grid.json pointer for the console."""
    settings = ensure_runtime_dirs(settings or get_settings())
    latest_dir = experiment_root(settings) / "latest" / "paper"
    latest_dir.mkdir(parents=True, exist_ok=True)
    path = latest_dir / "etf_ma_momentum_grid.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def lab_timeline(
    strategy_id: str,
    *,
    settings: Settings | None = None,
    benchmark_symbol: str = "510300.SH",
) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    if strategy_id not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {strategy_id}")
    board = paper_board(strategy_id, settings)
    timeline = list(board.get("timeline") or [])
    dates = [str(r["trade_date"]) for r in timeline]
    initial = float((board.get("summary") or {}).get("initial_cash") or 1.0) or 1.0
    rows = read_market_daily(settings=settings)
    closes, bench_nav = benchmark_series(rows, dates, symbol=benchmark_symbol) if dates else ([], [])
    regimes = label_regimes(dates, closes) if dates and closes else []
    # Rebalance markers: days with buys or sells
    markers = [
        {
            "trade_date": str(r["trade_date"]),
            "kind": "rebalance",
            "buys": int(r.get("buys") or 0),
            "sells": int(r.get("sells") or 0),
        }
        for r in timeline
        if int(r.get("buys") or 0) or int(r.get("sells") or 0)
    ]
    dd = build_insight(timeline, rows, benchmark_symbol=benchmark_symbol).get("drawdown") if timeline else {}
    peak_date = dd.get("peak_date") if isinstance(dd, dict) else None
    trough_date = dd.get("trough_date") if isinstance(dd, dict) else None
    nav = [
        {
            "trade_date": str(r["trade_date"]),
            "nav": round(float(r["total_asset"]) / initial, 8),
            "total_asset": float(r["total_asset"]),
            "daily_return": float(r.get("daily_return") or 0),
            "drawdown": float(r.get("drawdown") or 0),
            "regime": regimes[i] if i < len(regimes) else "range",
            "benchmark_nav": round(bench_nav[i], 8) if i < len(bench_nav) else None,
        }
        for i, r in enumerate(timeline)
    ]
    version = query_all(
        """
        SELECT parameter_set_id, status FROM strategy_version
        WHERE strategy_id = ? ORDER BY created_at DESC LIMIT 1
        """,
        (strategy_id,),
        settings=settings,
    )
    pinned = STRATEGY_SPECS[strategy_id]
    return {
        "strategy_id": strategy_id,
        "account_id": account_id_for(strategy_id),
        "parameter_set_id": (version[0]["parameter_set_id"] if version else pinned["parameter_set_id"]),
        "params": dict(pinned["params"]),
        "status": version[0]["status"] if version else None,
        "benchmark_symbol": benchmark_symbol,
        "summary": board.get("summary") or {},
        "points": nav,
        "markers": markers,
        "drawdown": dd,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "regime_stats": build_insight(timeline, rows, benchmark_symbol=benchmark_symbol)["regimes"]["stats"]
        if timeline
        else {},
    }
