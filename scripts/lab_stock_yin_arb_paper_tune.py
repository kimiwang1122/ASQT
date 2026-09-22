#!/usr/bin/env python3
"""Train stock_yin_arb on PaperBroker (fees, stamp, slippage, lots).

Usage:
  uv run python scripts/lab_stock_yin_arb_paper_tune.py
  uv run python scripts/lab_stock_yin_arb_paper_tune.py --signal-only
  uv run python scripts/lab_stock_yin_arb_paper_tune.py --start 2018-01-02 --end 2026-09-21
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asqt.config import ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.ops import (
    kill_engaged,
    paper_account_config,
    set_kill_switch,
    set_paper_account_config,
    set_paper_trading,
)
from asqt.paper import paper_board, reset_paper_account, run_paper_days
from asqt.strategies import STOCK_YIN_ARB, STRATEGY_SPECS, pin_strategy_params
from asqt.tune import stock_yin_arb_short_id, suggest_parameter_set_id

RATIOS = (1.5, 1.8, 2.0)
BANDS = (0.02, 0.025, 0.03)
KS = (5, 10)
LOOKBACKS = (3, 5)
STOPS = (0.0, 0.04, 0.08, 0.12)
TAKES = (0.0, 0.20, 0.40, 0.60)
TOP3 = (
    {"top_k": 10, "burst_ratio": 1.5, "pullback_band": 0.03, "burst_lookback": 5},
    {"top_k": 10, "burst_ratio": 1.5, "pullback_band": 0.025, "burst_lookback": 5},
    {"top_k": 10, "burst_ratio": 1.8, "pullback_band": 0.025, "burst_lookback": 5},
)
OUT_FULL = Path("data/experiment/tune/stock_yin_arb_paper_full_u300.json")
OUT_SIGNAL = Path("data/experiment/tune/stock_yin_arb_paper_tune.json")
OUT_STOPS = Path("data/experiment/tune/stock_yin_arb_paper_stops.json")


def _cells(*, mode: str) -> list[dict]:
    spec = dict(STRATEGY_SPECS[STOCK_YIN_ARB]["params"])
    cells: list[dict] = []
    if mode == "stops":
        for top, sl, tp in itertools.product(TOP3, STOPS, TAKES):
            cells.append({**spec, **top, "stop_loss": sl, "take_profit": tp})
        return cells
    if mode == "signal":
        for ratio, band, k, lookback in itertools.product(RATIOS, BANDS, KS, LOOKBACKS):
            cells.append(
                {
                    **spec,
                    "burst_ratio": ratio,
                    "pullback_band": band,
                    "top_k": k,
                    "burst_lookback": lookback,
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                }
            )
        return cells
    for ratio, band, k, lookback, sl, tp in itertools.product(
        RATIOS, BANDS, KS, LOOKBACKS, STOPS, TAKES
    ):
        cells.append(
            {
                **spec,
                "burst_ratio": ratio,
                "pullback_band": band,
                "top_k": k,
                "burst_lookback": lookback,
                "stop_loss": sl,
                "take_profit": tp,
            }
        )
    return cells


def _progress(label: str):
    last = {"t": 0.0}

    def bump(done: int, total: int, text: str) -> None:
        now = time.time()
        if done in {0, total} or now - last["t"] >= 60:
            last["t"] = now
            pct = (100.0 * done / total) if total else 0
            print(f"  {label} {done}/{total} ({pct:.0f}%) {text}", flush=True)

    return bump


def _ensure_paper(settings) -> None:
    row = query_all(
        "SELECT status FROM strategy_version WHERE strategy_id = ? AND version = 'v1'",
        (STOCK_YIN_ARB,),
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
                STOCK_YIN_ARB,
                STRATEGY_SPECS[STOCK_YIN_ARB]["parameter_set_id"],
                datetime.now(timezone.utc).date().isoformat(),
            ),
            settings=settings,
        )
        return
    if row[0]["status"] != "paper":
        execute(
            "UPDATE strategy_version SET status = 'paper' WHERE strategy_id = ? AND version = 'v1'",
            (STOCK_YIN_ARB,),
            settings=settings,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-02")
    parser.add_argument("--end", default="2026-09-21")
    parser.add_argument("--only", default="", help="substring of parameter_set_id / short_id")
    parser.add_argument(
        "--stops",
        action="store_true",
        help="Paper top3 × stop_loss/take_profit grid (4×4)",
    )
    parser.add_argument(
        "--signal-only",
        action="store_true",
        help="Signal knobs only (sl=0 tp=0), 36 cells",
    )
    args = parser.parse_args()
    mode = "stops" if args.stops else ("signal" if args.signal_only else "full")
    needle = str(args.only or "").strip()
    settings = ensure_runtime_dirs(get_settings())
    initialize_database(settings)
    set_paper_trading(True, "lab yin_arb paper tune", settings=settings)
    _ensure_paper(settings)
    before = paper_account_config(settings)
    cash = float(before["initial_cash"])
    path = {"full": OUT_FULL, "signal": OUT_SIGNAL, "stops": OUT_STOPS}[mode]
    path.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict] = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            for row in prev.get("results") or []:
                if row.get("parameter_set_id"):
                    done[str(row["parameter_set_id"])] = row
        except json.JSONDecodeError:
            done = {}
    planned = []
    for params in _cells(mode=mode):
        psid = suggest_parameter_set_id(STOCK_YIN_ARB, params)
        short = stock_yin_arb_short_id(params)
        if needle and needle not in psid and needle not in short:
            continue
        planned.append((params, psid, short))
    print(
        f"paper-tune mode={mode} cells={len(planned)} done={len(done)} cash={cash:.0f} "
        f"dd {before['portfolio_drawdown_stop_pct']}%→80% {args.start}→{args.end}",
        flush=True,
    )
    try:
        set_paper_account_config(
            initial_cash=cash,
            commission_per_myriad=before["commission_per_myriad"],
            portfolio_drawdown_stop_pct=80.0,
            strategy_drawdown_stop_pct=80.0,
            drawdown_warn_pct=min(float(before["drawdown_warn_pct"] or 0), 80.0),
            actor="lab",
            settings=settings,
        )
        for i, (params, psid, short) in enumerate(planned, 1):
            if psid in done:
                print(f"  skip {short}", flush=True)
                continue
            if kill_engaged(settings):
                set_kill_switch(False, "yin_arb paper tune: clear kill", settings=settings)
            print(f"==> {i}/{len(planned)} {short}", flush=True)
            t0 = time.time()
            pin_strategy_params(
                STOCK_YIN_ARB, params, parameter_set_id=psid, settings=settings, persist=True
            )
            reset_paper_account(strategy_id=STOCK_YIN_ARB, reason=f"paper-tune {psid}", settings=settings)
            run_paper_days(
                strategy_id=STOCK_YIN_ARB,
                days=20,
                start_date=args.start,
                end_date=args.end,
                settings=settings,
                mode="sequential",
                record_task=False,
                progress=_progress(short),
            )
            summary = paper_board(STOCK_YIN_ARB, settings).get("summary") or {}
            row = {
                "parameter_set_id": psid,
                "short_id": short,
                "params": params,
                "elapsed_sec": round(time.time() - t0, 1),
                "total_return": summary.get("total_return"),
                "peak_return": summary.get("peak_return"),
                "max_drawdown": summary.get("max_drawdown"),
                "end_asset": summary.get("end_asset"),
                "fees": summary.get("fees"),
                "sessions": summary.get("sessions"),
                "halt_status": summary.get("halt_status"),
            }
            done[psid] = row
            results = sorted(
                done.values(), key=lambda r: float(r.get("total_return") or -1e9), reverse=True
            )
            path.write_text(
                json.dumps(
                    {
                        "window": [args.start, args.end],
                        "universe": "poc stocks after HS300 expand",
                        "note": "PaperBroker; 佣金/印花税/滑点/整手; 急停实验期 80%",
                        "grid_size": len(results),
                        "top": results[:20],
                        "results": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                f"    {float(row['total_return'] or 0):+.2%}  peak={float(row['peak_return'] or 0):+.2%}  "
                f"dd={float(row['max_drawdown'] or 0):+.2%}  {row['elapsed_sec']}s  wrote {path}",
                flush=True,
            )
    finally:
        set_paper_account_config(
            initial_cash=before["initial_cash"],
            commission_per_myriad=before["commission_per_myriad"],
            portfolio_drawdown_stop_pct=before["portfolio_drawdown_stop_pct"],
            strategy_drawdown_stop_pct=before["strategy_drawdown_stop_pct"],
            drawdown_warn_pct=before["drawdown_warn_pct"],
            actor="lab",
            settings=settings,
        )
        if kill_engaged(settings):
            set_kill_switch(False, "yin_arb paper tune: restore", settings=settings)
        print(
            f"restored cash {before['initial_cash']} dd {before['portfolio_drawdown_stop_pct']}%",
            flush=True,
        )
    print("\nTOP")
    ranked = sorted(done.values(), key=lambda r: float(r.get("total_return") or -1e9), reverse=True)
    for row in ranked[:12]:
        print(
            f"  {float(row['total_return'] or 0):+.2%}  peak={float(row['peak_return'] or 0):+.2%}  "
            f"dd={float(row['max_drawdown'] or 0):+.2%}  {row.get('short_id')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
