#!/usr/bin/env python3
"""Grid-search stock_2560 params for max return on the latest N sessions.

Usage:
  uv run python scripts/lab_stock_2560_grid.py
  uv run python scripts/lab_stock_2560_grid.py --days 240 --apply
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asqt.config import ensure_runtime_dirs, get_settings
from asqt.db import query_all
from asqt.lab_params import set_lab_default
from asqt.ops import set_paper_trading
from asqt.paper import paper_board, reset_paper_account, run_paper_days
from asqt.reporting import write_run_tree
from asqt.storage import read_market_daily
from asqt.strategies import STOCK_2560, STRATEGY_SPECS, pin_strategy_params
from asqt.tune import simulate_path, suggest_parameter_set_id


def build_grid(*, feasible_only: bool = True) -> list[dict]:
    """Search space. feasible_only keeps post-clip weight ≤ stock name_cap 10%."""
    cells = []
    for slow, vol_slow, band, k, max_w in itertools.product(
        (15, 20, 25, 30),
        (40, 60, 90),
        (0.01, 0.015, 0.02, 0.03, 0.05),
        (2, 3, 5, 8, 10),
        (0.10, 0.15, 0.20),
    ):
        if feasible_only and min(1.0 / k, max_w) > 0.10 + 1e-12:
            continue
        cells.append(
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
        )
    return cells


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=240)
    parser.add_argument("--apply", action="store_true", help="pin winner + paper verify")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    settings = ensure_runtime_dirs(get_settings())
    rows = read_market_daily(settings=settings)
    all_dates = sorted({str(row["trade_date"]) for row in rows})
    dates = all_dates[-(args.days + 1) :]
    if len(dates) < args.days + 1:
        raise SystemExit(f"need {args.days + 1} sessions, have {len(all_dates)}")
    limits = query_all("SELECT * FROM limit_suspension", settings=settings)
    is_end = dates[int(len(dates) * 0.7)]
    grid = build_grid()
    print(f"grid={len(grid)} days={args.days} window={dates[0]}→{dates[-1]}", flush=True)

    ranked: list[dict] = []
    for i, params in enumerate(grid, 1):
        path = simulate_path(
            STOCK_2560,
            params=params,
            rows=rows,
            limits=limits,
            dates=dates,
            is_end=is_end,
        )
        total_return = float(path["nav"]) - 1.0
        is_m = (path.get("metrics") or {}).get("is") or {}
        oos_m = (path.get("metrics") or {}).get("oos") or {}
        ranked.append(
            {
                "params": params,
                "parameter_set_id": suggest_parameter_set_id(STOCK_2560, params),
                "total_return": round(total_return, 6),
                "nav": path["nav"],
                "max_drawdown": is_m.get("max_drawdown"),  # full-window dd below
                "avg_turnover": path["avg_turnover"],
                "is_return": is_m.get("total_return"),
                "oos_return": oos_m.get("total_return"),
                "is_max_drawdown": is_m.get("max_drawdown"),
                "oos_max_drawdown": oos_m.get("max_drawdown"),
            }
        )
        # full-window drawdown from nav path is not in is_m alone; recompute via nav
        if i % 50 == 0 or i == len(grid):
            print(f"  {i}/{len(grid)} best_so_far={max(r['total_return'] for r in ranked):+.2%}", flush=True)

    # Recompute full-window max DD cheaply: simulate already has only IS/OOS split.
    # Rank by total_return; tie-break shallower |oos dd| then lower turnover.
    ranked.sort(
        key=lambda r: (
            float(r["total_return"]),
            -abs(float(r.get("oos_max_drawdown") or 0)),
            -float(r.get("avg_turnover") or 0),
        ),
        reverse=True,
    )
    winner = ranked[0]
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "ok": True,
        "lab": "stock_2560_grid",
        "batch_id": batch_id,
        "strategy_id": STOCK_2560,
        "days": args.days,
        "window": [dates[0], dates[-1]],
        "grid_size": len(grid),
        "winner": winner,
        "top": ranked[: args.top],
        "baseline": next(
            (
                row
                for row in ranked
                if row["parameter_set_id"]
                == suggest_parameter_set_id(STOCK_2560, STRATEGY_SPECS[STOCK_2560]["params"])
            ),
            None,
        ),
    }
    summary_path = write_run_tree(
        "tune",
        f"stock_2560_grid_{batch_id}",
        report,
        settings=settings,
        strategy_id=STOCK_2560,
        manifest={"lab": "stock_2560_grid", "batch_id": batch_id},
    )
    out = summary_path.parent
    csv_path = out / "grid.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "parameter_set_id",
                "total_return",
                "is_return",
                "oos_return",
                "avg_turnover",
                "ma_slow",
                "vol_slow",
                "pullback_band",
                "top_k",
                "max_weight",
            ],
        )
        writer.writeheader()
        for row in ranked:
            p = row["params"]
            writer.writerow(
                {
                    "parameter_set_id": row["parameter_set_id"],
                    "total_return": row["total_return"],
                    "is_return": row["is_return"],
                    "oos_return": row["oos_return"],
                    "avg_turnover": row["avg_turnover"],
                    "ma_slow": p["ma_slow"],
                    "vol_slow": p["vol_slow"],
                    "pullback_band": p["pullback_band"],
                    "top_k": p["top_k"],
                    "max_weight": p["max_weight"],
                }
            )

    print(json.dumps({"winner": winner, "experiment": str(out)}, ensure_ascii=False, indent=2))
    print("TOP:")
    for row in ranked[: args.top]:
        print(
            f"  {row['total_return']:+.2%}  is={row['is_return']} oos={row['oos_return']}  {row['parameter_set_id']}"
        )

    if args.apply:
        set_paper_trading(True, "lab stock_2560 grid apply", settings=settings)
        pin = pin_strategy_params(STOCK_2560, winner["params"], settings=settings, persist=True)
        set_lab_default(STOCK_2560, winner["params"], settings=settings)
        from asqt.lab_params import apply_run_pins

        apply_run_pins([STOCK_2560], mode="sequential", lab_params=winner["params"], settings=settings)
        reset_paper_account(strategy_id=STOCK_2560, reason=f"lab apply {pin['parameter_set_id']}", settings=settings)
        print(f"paper verify {args.days}d with {pin['parameter_set_id']} ...", flush=True)
        run_paper_days(strategy_id=STOCK_2560, days=args.days, settings=settings, mode="sequential")
        board = paper_board(STOCK_2560, settings)
        sm = board.get("summary") or {}
        print(
            json.dumps(
                {
                    "parameter_set_id": pin["parameter_set_id"],
                    "paper_total_return": sm.get("total_return"),
                    "paper_max_drawdown": sm.get("max_drawdown"),
                    "initial_cash": sm.get("initial_cash"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
