#!/usr/bin/env python3
"""1e6 cash: solo 2560, solo yin_arb, then parallel both. Same pins as lab defaults."""
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
from asqt.ops import kill_engaged, paper_account_config, set_kill_switch, set_paper_account_config, set_paper_trading
from asqt.paper import paper_board, run_paper_days
from asqt.strategies import STOCK_2560, STOCK_YIN_ARB, STRATEGY_LABEL

START = "2018-01-02"
END = "2026-09-21"
CASH = 1_000_000.0
OUT = ROOT / "data/experiment/tune/cash_1m_solo_vs_parallel.json"


def _progress(label: str):
    last = {"t": 0.0}

    def bump(done: int, total: int, text: str) -> None:
        now = time.time()
        if done in {0, total} or now - last["t"] >= 20:
            last["t"] = now
            pct = (100.0 * done / total) if total else 0
            print(f"  {label} {done}/{total} ({pct:.1f}%) {text}", flush=True)

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
    return {k: summary.get(k) for k in keys}


def _board(sid: str, settings) -> dict:
    payload = paper_board(sid, settings)
    rec = payload.get("reconcile") or {}
    return {
        "strategy_id": sid,
        "label": STRATEGY_LABEL.get(sid, sid),
        "summary": _pick(payload.get("summary") or {}),
        "reconcile_ok": rec.get("ok"),
    }


def _combined(books: list[dict]) -> dict:
    by_date: dict[str, float] = {}
    initials = []
    for book in books:
        sid = book["strategy_id"]
        payload = paper_board(sid)
        initials.append(float((payload.get("summary") or {}).get("initial_cash") or 0))
        for row in payload.get("timeline") or []:
            day = str(row["trade_date"])
            by_date[day] = by_date.get(day, 0.0) + float(row["total_asset"] or 0)
    days = sorted(by_date)
    if not days:
        return {}
    initial = sum(initials)
    peak = initial
    max_dd = 0.0
    for day in days:
        nav = by_date[day]
        peak = max(peak, nav)
        if peak:
            max_dd = min(max_dd, nav / peak - 1.0)
    last = by_date[days[-1]]
    return {
        "initial_cash": initial,
        "end_asset": last,
        "sessions": len(days),
        "window_start": days[0],
        "window_end": days[-1],
        "total_return": last / initial - 1.0 if initial else 0.0,
        "peak_return": peak / initial - 1.0 if initial else 0.0,
        "max_drawdown": max_dd,
        "peak_asset": peak,
    }


def _run(ids: list[str], mode: str, settings) -> dict:
    if kill_engaged(settings):
        set_kill_switch(False, "cash 1m compare: clear kill before run", settings=settings)
    apply_run_pins(ids, mode=mode, settings=settings)
    from asqt.lab_params import load_lab_defaults

    defaults = load_lab_defaults(settings=settings)
    pin_ids = {sid: defaults[sid]["parameter_set_id"] for sid in ids}
    print(f"\n==> {mode} {ids} pins={pin_ids}", flush=True)
    t0 = time.time()
    summary = run_paper_days(
        strategy_id=ids[0] if len(ids) == 1 else "all",
        strategy_ids=ids,
        days=20,
        start_date=START,
        end_date=END,
        settings=settings,
        progress=_progress(mode),
        record_task=False,
        mode=mode,
    )
    books = [_board(sid, settings) for sid in ids]
    elapsed = round(time.time() - t0, 1)
    print(f"  done {elapsed}s book_cash={summary.get('book_cash')}", flush=True)
    return {
        "mode": mode,
        "elapsed_sec": elapsed,
        "parameter_set_ids": pin_ids,
        "portfolio_cash": summary.get("portfolio_cash"),
        "book_cash": summary.get("book_cash"),
        "window": summary.get("window"),
        "ok": summary.get("ok"),
        "detail": summary.get("detail"),
        "books": books,
        "combined": _combined(books) if len(books) > 1 else None,
    }


def main() -> int:
    settings = ensure_runtime_dirs(get_settings())
    initialize_database(settings)
    set_paper_trading(True, "cash 1m compare", settings=settings)
    if kill_engaged(settings):
        set_kill_switch(False, "cash 1m compare: clear kill", settings=settings)
    before = paper_account_config(settings)
    # 30% 组合急停会在单跑 2560 回撤~31% 时全体掐死，后面两笔会被 skip。
    print(
        f"cash {before['initial_cash']} -> {CASH:.0f}; "
        f"dd port {before['portfolio_drawdown_stop_pct']}% -> 80% for experiment",
        flush=True,
    )
    set_paper_account_config(
        initial_cash=CASH,
        commission_per_myriad=before["commission_per_myriad"],
        portfolio_drawdown_stop_pct=80.0,
        strategy_drawdown_stop_pct=80.0,
        drawdown_warn_pct=min(float(before["drawdown_warn_pct"] or 0), 80.0),
        actor="lab",
        settings=settings,
    )
    payload = {
        "cash": CASH,
        "window": [START, END],
        "note": "本金 100 万；单跑各拿满 100 万；并行均分各 50 万。参数=实验室默认。实验期间组合急停暂提到 80%，避免 30% 线掐死后跳过后续回放。",
        "runs": [],
    }
    payload["runs"].append(_run([STOCK_2560], "sequential", settings))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["runs"].append(_run([STOCK_YIN_ARB], "sequential", settings))
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["runs"].append(_run([STOCK_2560, STOCK_YIN_ARB], "parallel", settings))
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    set_paper_account_config(
        initial_cash=CASH,
        commission_per_myriad=before["commission_per_myriad"],
        portfolio_drawdown_stop_pct=before["portfolio_drawdown_stop_pct"],
        strategy_drawdown_stop_pct=before["strategy_drawdown_stop_pct"],
        drawdown_warn_pct=before["drawdown_warn_pct"],
        actor="lab",
        settings=settings,
    )
    print(f"wrote {OUT}; restored dd port {before['portfolio_drawdown_stop_pct']}%", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
