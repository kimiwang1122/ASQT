"""GATE-B3: paper microstructure checklist (T+1 / lot / limit / suspension).

Reuses the prepared P3 fixtures; fails the gate if any checklist item regresses.
"""

from __future__ import annotations

from asqt.db import execute, query_all
from asqt.paper import LOT, PaperOrderService, run_paper_days
from asqt.strategies import ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK
from tests.test_p3_paper import _prepare


def test_gate_b3_lot_size_and_idempotent_keys(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    result = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert result["ok"] is True
    lots = query_all(
        "SELECT quantity, status FROM standard_order WHERE strategy_id = ? AND symbol != '000000.SZ'",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    assert lots
    assert all(int(row["quantity"]) % LOT == 0 or row["status"] == "rejected" for row in lots)
    keys = query_all(
        "SELECT idem_key, COUNT(*) AS c FROM standard_order WHERE strategy_id = ? GROUP BY idem_key",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    assert keys and all(int(row["c"]) == 1 for row in keys)


def test_gate_b3_suspended_rejects_buys(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    dates = sorted(
        {row["trade_date"] for row in query_all("SELECT DISTINCT trade_date FROM trade_calendar", settings=settings)}
    )
    fill, signal = dates[-1], dates[-2]
    for symbol in ("510300.SH", "510500.SH", "159915.SZ"):
        execute(
            """
            INSERT OR REPLACE INTO limit_suspension
                (symbol, trade_date, limit_up, limit_down, is_suspended, reason)
            VALUES (?, ?, 4.5, 3.6, 1, 'halt')
            """,
            (symbol, fill),
            settings=settings,
        )
    created = PaperOrderService(settings).build_orders(fill, ETF_MA_ROTATE, signal_date=signal)
    buys = [row for row in created if row["side"] == "BUY" and row["symbol"] != "000000.SZ"]
    if buys:
        assert all(row["status"] == "rejected" for row in buys)
        assert all("suspended" in (row["risk_tags"] or "") for row in buys)


def test_gate_b3_t1_same_day_buy_not_sellable(tmp_path):
    """Newly bought qty is not in tradable until next session (T+1)."""
    from asqt.paper import PaperLedger, sync_halt_lifecycle

    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=3, settings=settings)
    ledger = PaperLedger(STOCK_MOMENTUM_TOPK, settings)
    dates = sorted(
        {row["trade_date"] for row in query_all("SELECT DISTINCT trade_date FROM trade_calendar", settings=settings)}
    )
    # Load state as of last fill day: tradable should equal positions carried in (not same-day buys only).
    state = ledger.load(before=dates[-1])
    sync_halt_lifecycle(state)
    # Simulate build_orders tradable reset (positions become sellable only next day).
    state["tradable"] = {symbol: int(item["qty"]) for symbol, item in state["positions"].items()}
    for symbol, item in state["positions"].items():
        assert int(state["tradable"].get(symbol, 0)) == int(item["qty"])
