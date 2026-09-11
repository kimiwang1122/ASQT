from __future__ import annotations

from asqt.db import execute, query_all
from asqt.ops import set_kill_switch, set_paper_trading
from asqt.paper import account_id_for, advance_paper_session, run_paper_days
from asqt.scheduler import LocalScheduler
from asqt.strategies import STOCK_MOMENTUM_TOPK
from tests.test_p3_paper import _prepare


def test_paper_daily_skips_when_trading_off(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    set_paper_trading(False, "off for skip", settings=settings)
    result = advance_paper_session(trigger="test", settings=settings)
    assert result["status"] == "skipped"
    assert result["reason"] == "paper_trading_off"
    tasks = query_all(
        "SELECT task_name, status FROM task_run WHERE task_name = 'paper-daily'",
        settings=settings,
    )
    assert tasks
    assert tasks[-1]["status"] == "skipped"


def test_paper_daily_skips_kill_and_is_idempotent(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id="all", days=5, settings=settings)
    first = advance_paper_session(trigger="test", settings=settings)
    assert first["status"] == "skipped"
    assert first["reason"] == "already_current"
    assert STOCK_MOMENTUM_TOPK in first["already"]
    account = account_id_for(STOCK_MOMENTUM_TOPK)
    last = query_all(
        "SELECT trade_date FROM account_snapshot WHERE account_id = ? ORDER BY trade_date DESC LIMIT 1",
        (account,),
        settings=settings,
    )[0]["trade_date"]
    execute(
        "DELETE FROM account_snapshot WHERE account_id = ? AND trade_date = ?",
        (account, last),
        settings=settings,
    )
    replay = advance_paper_session(fill_date=last, trigger="test", settings=settings)
    assert replay["status"] == "success"
    assert STOCK_MOMENTUM_TOPK in replay["ran"]
    restored = query_all(
        "SELECT COUNT(*) AS c FROM account_snapshot WHERE account_id = ? AND trade_date = ?",
        (account, last),
        settings=settings,
    )[0]["c"]
    assert int(restored) == 1
    again = advance_paper_session(fill_date=last, trigger="test", settings=settings)
    assert again["status"] == "skipped"
    assert again["reason"] == "already_current"
    set_kill_switch(True, "halt daily", settings=settings)
    killed = advance_paper_session(trigger="test", settings=settings)
    assert killed["status"] == "skipped"
    assert killed["reason"] == "kill_switch"
    set_kill_switch(False, "clear halt", settings=settings)


def test_local_scheduler_lists_paper_daily_and_rejects_unknown(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    advance_paper_session(trigger="test", settings=settings)
    sched = LocalScheduler(settings)
    names = {row["task_name"] for row in sched.list_tasks()}
    assert "paper-daily" in names
    try:
        sched.run_task("not-a-task")
        raise AssertionError("expected unknown task")
    except ValueError as exc:
        assert "unknown task" in str(exc)
