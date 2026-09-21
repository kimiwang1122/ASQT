#!/usr/bin/env python3
"""Train stock_2560 SL/TP on PaperBroker (same path as the UI 跑模拟).

Usage:
  .venv/bin/python scripts/lab_stock_2560_paper_tune.py
  .venv/bin/python scripts/lab_stock_2560_paper_tune.py --start 2018-01-02 --end 2026-09-18
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asqt.config import ensure_runtime_dirs, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.lab_params import STOCK_2560_PRESETS
from asqt.ops import paper_account_config, set_paper_trading
from asqt.paper import paper_board, reset_paper_account, run_paper_days
from asqt.strategies import STOCK_2560, STRATEGY_SPECS, pin_strategy_params
from asqt.tune import stock_2560_short_id, suggest_parameter_set_id

STOPS = (0.0, 0.04, 0.08, 0.12)
TAKES = (0.0, 0.20, 0.40, 0.60)


def _bases() -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for raw in STOCK_2560_PRESETS:
        params = dict(STRATEGY_SPECS[STOCK_2560]["params"])
        params.update(raw)
        params["stop_loss"] = 0.0
        params["take_profit"] = 0.0
        psid = suggest_parameter_set_id(STOCK_2560, params)
        if psid in seen:
            continue
        seen.add(psid)
        out.append(params)
    return out


def _ensure_paper(settings) -> None:
    row = query_all(
        "SELECT status FROM strategy_version WHERE strategy_id = ? AND version = 'v1'",
        (STOCK_2560,),
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
                STOCK_2560,
                STRATEGY_SPECS[STOCK_2560]["parameter_set_id"],
                datetime.now(timezone.utc).date().isoformat(),
            ),
            settings=settings,
        )
        return
    if row[0]["status"] != "paper":
        execute(
            "UPDATE strategy_version SET status = 'paper' WHERE strategy_id = ? AND version = 'v1'",
            (STOCK_2560,),
            settings=settings,
        )


def _cells() -> list[dict]:
    cells = []
    for base in _bases():
        for sl, tp in ((s, t) for s in STOPS for t in TAKES):
            params = {**base, "stop_loss": sl, "take_profit": tp}
            cells.append(params)
    return cells


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-02")
    parser.add_argument("--end", default="2026-09-18")
    parser.add_argument("--only", default="", help="substring of parameter_set_id / short_id")
    args = parser.parse_args()
    needle = str(args.only or "").strip()
    settings = ensure_runtime_dirs(get_settings())
    initialize_database(settings)
    set_paper_trading(True, "lab 2560 paper tune", settings=settings)
    _ensure_paper(settings)
    cash = float(paper_account_config(settings)["initial_cash"])
    path = Path("data/experiment/tune/stock_2560_paper_tune.json")
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
    for params in _cells():
        psid = suggest_parameter_set_id(STOCK_2560, params)
        short = stock_2560_short_id(params)
        if needle and needle not in psid and needle not in short:
            continue
        planned.append((params, psid, short))
    print(
        f"paper-tune cells={len(planned)} done={len(done)} cash={cash:.0f} "
        f"{args.start}→{args.end}",
        flush=True,
    )
    results = list(done.values())
    for i, (params, psid, short) in enumerate(planned, 1):
        if psid in done:
            print(f"  skip {short}", flush=True)
            continue
        print(f"==> {i}/{len(planned)} {short}", flush=True)
        pin_strategy_params(STOCK_2560, params, parameter_set_id=psid, settings=settings, persist=True)
        reset_paper_account(strategy_id=STOCK_2560, reason=f"paper-tune {psid}", settings=settings)
        run_paper_days(
            strategy_id=STOCK_2560,
            days=20,
            start_date=args.start,
            end_date=args.end,
            settings=settings,
            mode="sequential",
            record_task=False,
        )
        summary = (paper_board(STOCK_2560, settings).get("summary") or {})
        row = {
            "parameter_set_id": psid,
            "short_id": short,
            "params": params,
            "total_return": summary.get("total_return"),
            "peak_return": summary.get("peak_return"),
            "max_drawdown": summary.get("max_drawdown"),
            "end_asset": summary.get("end_asset"),
            "fees": summary.get("fees"),
            "sessions": summary.get("sessions"),
        }
        done[psid] = row
        results = list(done.values())
        results.sort(key=lambda r: float(r.get("total_return") or -1e9), reverse=True)
        payload = {
            "window": [args.start, args.end],
            "note": "PaperBroker run_paper_days; same engine as UI 跑模拟",
            "grid_size": len(results),
            "top": results[:20],
            "results": results,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"    {float(row['total_return'] or 0):+.2%}  peak={float(row['peak_return'] or 0):+.2%}  "
            f"dd={float(row['max_drawdown'] or 0):+.2%}  wrote {path}",
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
