#!/usr/bin/env python3
"""Solo stock_2560 k8.s25.vs90.b20.sl4.tp20 across 30万–100万 cash."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asqt.config import ensure_runtime_dirs, get_settings
from asqt.db import initialize_database
from asqt.lab_params import apply_run_pins
from asqt.ops import (
    kill_engaged,
    paper_account_config,
    set_kill_switch,
    set_paper_account_config,
    set_paper_trading,
)
from asqt.paper import paper_board, run_paper_days
from asqt.strategies import STOCK_2560

START = "2018-01-02"
END = "2026-09-21"
CASHES = [300_000, 400_000, 500_000, 600_000, 700_000, 800_000, 900_000, 1_000_000]
PARAMS = {
    "ma_fast": 5,
    "ma_slow": 25,
    "vol_fast": 5,
    "vol_slow": 90,
    "pullback_band": 0.02,
    "top_k": 8,
    "max_weight": 0.10,
    "gross_limit": 0.95,
    "stop_loss": 0.04,
    "take_profit": 0.20,
}
PSID = "stock_2560.k8.f5.s25.vf5.vs90.b20.sl4.tp20"
OUT = ROOT / "data/experiment/tune/stock_2560_cash_30w_100w.json"


def _progress(label: str):
    last = {"t": 0.0}

    def bump(done: int, total: int, text: str) -> None:
        now = time.time()
        if done in {0, total} or now - last["t"] >= 30:
            last["t"] = now
            pct = (100.0 * done / total) if total else 0
            print(f"  {label} {done}/{total} ({pct:.0f}%) {text}", flush=True)

    return bump


def _pick(summary: dict) -> dict:
    keys = (
        "window_start",
        "window_end",
        "sessions",
        "initial_cash",
        "end_asset",
        "cash",
        "market_value",
        "total_return",
        "peak_return",
        "max_drawdown",
        "peak_asset",
        "position_count",
        "orders_filled",
        "orders_rejected",
        "fees",
        "halt_status",
        "halt_reason",
    )
    out = {k: summary.get(k) for k in keys}
    nav = float(summary.get("end_asset") or 0)
    cash = float(summary.get("cash") or 0)
    out["end_cash_ratio"] = round(cash / nav, 4) if nav else None
    fee = float(summary.get("fees") or 0)
    init = float(summary.get("initial_cash") or 0)
    out["fee_over_principal"] = round(fee / init, 4) if init else None
    return out


def main() -> int:
    settings = ensure_runtime_dirs(get_settings())
    initialize_database(settings)
    set_paper_trading(True, "2560 cash ladder", settings=settings)
    before = paper_account_config(settings)
    print(
        f"pin {PSID}; cash ladder {CASHES[0]:.0f}→{CASHES[-1]:.0f}; "
        f"dd {before['portfolio_drawdown_stop_pct']}% → 80% during run",
        flush=True,
    )
    apply_run_pins(
        [STOCK_2560],
        mode="sequential",
        lab_params=PARAMS,
        parameter_set_id=PSID,
        settings=settings,
    )
    payload = {
        "parameter_set_id": PSID,
        "params": PARAMS,
        "window": [START, END],
        "note": "单策略顺序模拟；实验期组合急停 80%，跑完恢复。",
        "rows": [],
    }
    try:
        for cash in CASHES:
            if kill_engaged(settings):
                set_kill_switch(False, "2560 cash ladder: clear kill", settings=settings)
            set_paper_account_config(
                initial_cash=cash,
                commission_per_myriad=before["commission_per_myriad"],
                portfolio_drawdown_stop_pct=80.0,
                strategy_drawdown_stop_pct=80.0,
                drawdown_warn_pct=min(float(before["drawdown_warn_pct"] or 0), 80.0),
                actor="lab",
                settings=settings,
            )
            print(f"\n==> cash {cash:.0f}", flush=True)
            t0 = time.time()
            run = run_paper_days(
                strategy_id=STOCK_2560,
                days=20,
                start_date=START,
                end_date=END,
                settings=settings,
                progress=_progress(f"{int(cash/10000)}w"),
                record_task=False,
                mode="sequential",
            )
            board = paper_board(STOCK_2560, settings)
            rec = board.get("reconcile") or {}
            row = {
                "cash": cash,
                "elapsed_sec": round(time.time() - t0, 1),
                "ok": run.get("ok"),
                "detail": run.get("detail"),
                "summary": _pick(board.get("summary") or {}),
                "reconcile_ok": rec.get("ok"),
            }
            payload["rows"].append(row)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            s = row["summary"]
            print(
                f"  ret={s.get('total_return')} peak={s.get('peak_return')} "
                f"dd={s.get('max_drawdown')} end={s.get('end_asset')} ok={row['ok']}",
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
            set_kill_switch(False, "2560 cash ladder: restore", settings=settings)
        print(
            f"wrote {OUT}; restored cash {before['initial_cash']} "
            f"dd {before['portfolio_drawdown_stop_pct']}%",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
