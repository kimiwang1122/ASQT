#!/usr/bin/env python3
"""Sequential 6×N-day paper lab for etf_ma_momentum_filter (ma∈{10,20} × top_k∈{3,4,5}).

Usage:
  uv run python scripts/lab_etf_ma_momentum_grid.py
  uv run python scripts/lab_etf_ma_momentum_grid.py --days 240
  uv run python scripts/lab_etf_ma_momentum_grid.py --days 5 --dry-admit
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asqt.config import ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.lab_insight import build_insight
from asqt.ops import set_paper_trading
from asqt.paper import paper_board, reset_paper_account, run_paper_days
from asqt.reporting import write_run_tree
from asqt.storage import read_market_daily
from asqt.strategies import ETF_MA_MOMENTUM_FILTER, STRATEGY_SPECS, pin_strategy_params
from asqt.tune import suggest_parameter_set_id

GRID = [
    {"ma_window": mw, "mom_lookback": mw, "top_k": k, "max_weight": 0.20, "gross_limit": 0.95}
    for mw in (10, 20)
    for k in (3, 4, 5)
]


def _ensure_paper(settings, strategy_id: str) -> None:
    row = query_all(
        "SELECT status FROM strategy_version WHERE strategy_id = ? AND version = 'v1'",
        (strategy_id,),
        settings=settings,
    )
    if not row:
        execute(
            """
            INSERT INTO strategy_version
            (strategy_id, version, status, parameter_set_id, code_version, risk_config, effective_date)
            VALUES (?, 'v1', 'paper', ?, 'lab', '{}', ?)
            """,
            (
                strategy_id,
                STRATEGY_SPECS[strategy_id]["parameter_set_id"],
                datetime.now(timezone.utc).date().isoformat(),
            ),
            settings=settings,
        )
        return
    if row[0]["status"] != "paper":
        execute(
            "UPDATE strategy_version SET status = 'paper' WHERE strategy_id = ? AND version = 'v1'",
            (strategy_id,),
            settings=settings,
        )


def _holdings_stats(timeline: list[dict], board: dict) -> dict:
    cash_ratios = []
    for row in timeline:
        asset = float(row.get("total_asset") or 0)
        cash = float(row.get("cash") or 0)
        if asset > 0:
            cash_ratios.append(cash / asset)
    positions = board.get("positions") or []
    return {
        "end_position_count": len(positions),
        "avg_cash_ratio": round(sum(cash_ratios) / len(cash_ratios), 6) if cash_ratios else None,
        "note": "TopK clipped by max_weight=0.20; top3 often ~60% invested",
    }


def run_cell(params: dict, *, days: int, settings, batch_id: str) -> dict:
    sid = ETF_MA_MOMENTUM_FILTER
    pin = pin_strategy_params(sid, params, settings=settings, persist=True)
    psid = pin["parameter_set_id"]
    reset_paper_account(strategy_id=sid, reason=f"lab grid {psid}", settings=settings)
    paper = run_paper_days(strategy_id=sid, days=days, settings=settings, mode="sequential")
    board = paper_board(sid, settings)
    timeline = list(board.get("timeline") or [])
    summary = board.get("summary") or {}
    market = read_market_daily(settings=settings)
    insight = build_insight(
        timeline,
        market,
        benchmark_symbol="510300.SH",
        holdings_stats=_holdings_stats(timeline, board),
    )
    cell = {
        "ok": True,
        "batch_id": batch_id,
        "strategy_id": sid,
        "parameter_set_id": psid,
        "params": params,
        "days": days,
        "paper_run": {
            "run_id": paper.get("run_id"),
            "sessions": summary.get("sessions"),
            "total_return": summary.get("total_return"),
            "max_drawdown": summary.get("max_drawdown"),
            "end_asset": summary.get("end_asset"),
            "fees": summary.get("fees"),
            "orders_filled": summary.get("orders_filled"),
        },
        "summary": summary,
        "insight": {
            "calendar": insight["calendar"],
            "regime_stats": insight["regimes"]["stats"],
            "drawdown": insight["drawdown"],
            "holdings": insight["holdings"],
            "benchmark_symbol": insight["benchmark_symbol"],
        },
        "nav": [
            {
                "trade_date": r["trade_date"],
                "total_asset": r["total_asset"],
                "daily_return": r.get("daily_return"),
                "drawdown": r.get("drawdown"),
            }
            for r in timeline
        ],
    }
    run_id = f"{psid}_{batch_id}"
    path = write_run_tree(
        "paper",
        run_id,
        cell,
        settings=settings,
        strategy_id=sid,
        manifest={"lab": "etf_ma_momentum_grid", "batch_id": batch_id},
    )
    folder = path.parent
    (folder / "nav.json").write_text(json.dumps(cell["nav"], ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "insight.json").write_text(
        json.dumps(insight, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    cell["experiment_path"] = str(folder)
    return cell


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=240)
    parser.add_argument("--only", default="", help="comma parameter_set_id filter")
    args = parser.parse_args()
    settings = ensure_runtime_dirs(get_settings())
    initialize_database(settings)
    set_paper_trading(True, "lab etf ma momentum grid", settings=settings)
    _ensure_paper(settings, ETF_MA_MOMENTUM_FILTER)

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    results: list[dict] = []
    for params in GRID:
        psid = suggest_parameter_set_id(ETF_MA_MOMENTUM_FILTER, params)
        if only and psid not in only:
            continue
        print(f"==> {psid} days={args.days}", flush=True)
        cell = run_cell(params, days=args.days, settings=settings, batch_id=batch_id)
        results.append(cell)
        print(
            f"    return={cell['paper_run']['total_return']} dd={cell['paper_run']['max_drawdown']} "
            f"path={cell['experiment_path']}",
            flush=True,
        )

    root = settings.experiment_dir / "paper" / f"etf_ma_momentum_grid_{batch_id}"
    root.mkdir(parents=True, exist_ok=True)
    summary_rows = [
        {
            "parameter_set_id": r["parameter_set_id"],
            "ma_window": r["params"]["ma_window"],
            "mom_lookback": r["params"]["mom_lookback"],
            "top_k": r["params"]["top_k"],
            "total_return": r["paper_run"]["total_return"],
            "max_drawdown": r["paper_run"]["max_drawdown"],
            "sessions": r["paper_run"]["sessions"],
            "fees": r["paper_run"]["fees"],
            "experiment_path": r["experiment_path"],
            "regime_stats": r["insight"]["regime_stats"],
            "calendar_weekday": r["insight"]["calendar"].get("weekday"),
        }
        for r in results
    ]
    (root / "summary.json").write_text(
        json.dumps({"batch_id": batch_id, "days": args.days, "rows": summary_rows}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    from asqt.lab_timeline import write_lab_grid_latest

    write_lab_grid_latest(
        {"batch_id": batch_id, "days": args.days, "rows": summary_rows},
        settings=settings,
    )
    with (root / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "parameter_set_id",
                "ma_window",
                "mom_lookback",
                "top_k",
                "total_return",
                "max_drawdown",
                "sessions",
                "fees",
                "experiment_path",
            ],
        )
        writer.writeheader()
        for row in summary_rows:
            writer.writerow({k: row.get(k) for k in writer.fieldnames})
    print(f"batch summary -> {root}", flush=True)


if __name__ == "__main__":
    main()
