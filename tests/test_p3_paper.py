from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.db import execute, query_all
from asqt.ops import LocalAlertService, kill_engaged, set_kill_switch, set_paper_trading
from asqt.paper import (
    PaperBroker,
    PaperBusy,
    PaperOrderService,
    account_id_for,
    acquire_paper_run_lock,
    release_paper_run_lock,
    reset_paper_account,
    run_paper_days,
)
from asqt.research_engine import LocalResearchEngine, LocalStrategyService
from asqt.review import LocalReviewService
from asqt.strategies import ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK, STRATEGY_SPECS
from tests.test_p2_research import _seed, _trend_book, make_settings


def _prepare(tmp_path: Path) -> tuple:
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    engine = LocalResearchEngine(settings)
    for strategy_id in (ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK):
        report = engine.run_backtest(strategy_id, STRATEGY_SPECS[strategy_id]["parameter_set_id"], "auto")
        assert report["ok"] is True
    service = LocalStrategyService(settings)
    for strategy_id in (ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK):
        version = service.admit_to_paper(strategy_id, "p3 test admit")
        assert version["status"] == "paper"
        assert version["risk_config"]
        assert version["parameter_set_id"]
        assert version["effective_date"]
    set_paper_trading(True, "p3 test enable", settings=settings)
    return settings, engine, service


def test_p3_paper_run_requires_admit(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    LocalResearchEngine(settings).run_backtest(
        STOCK_MOMENTUM_TOPK, STRATEGY_SPECS[STOCK_MOMENTUM_TOPK]["parameter_set_id"], "auto"
    )
    with pytest.raises(ValueError, match="模拟交易开关为关"):
        run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    set_paper_trading(True, "enable for admit check", settings=settings)
    with pytest.raises(ValueError, match="尚未准入模拟"):
        run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)


def test_p3_admit_pause_and_block_research_rerun(tmp_path):
    settings, engine, service = _prepare(tmp_path)
    paused = service.pause(ETF_MA_ROTATE, "operator pause")
    assert paused["status"] == "paused"
    with pytest.raises(PermissionError):
        service.generate_target_positions(ETF_MA_ROTATE, "2024-01-10")
    resumed = service.resume(ETF_MA_ROTATE, "operator resume")
    assert resumed["status"] == "paper"
    rerun = engine.run_backtest(ETF_MA_ROTATE, STRATEGY_SPECS[ETF_MA_ROTATE]["parameter_set_id"], "auto")
    assert rerun["ok"] is True
    assert rerun["status"] == "paper"
    assert service.current_version(ETF_MA_ROTATE)["status"] == "paper"
    service.pause(STOCK_MOMENTUM_TOPK, "pause before kill")
    set_kill_switch(True, "halt for test", settings=settings)
    with pytest.raises(PermissionError):
        service.resume(STOCK_MOMENTUM_TOPK, "resume while killed")
    set_kill_switch(False, "resume after halt", settings=settings)
    service.resume(STOCK_MOMENTUM_TOPK, "resume after halt")


def test_p3_lifecycle_api_explains_kill_switch(tmp_path, monkeypatch):
    settings, _engine, service = _prepare(tmp_path)
    service.pause(STOCK_MOMENTUM_TOPK, "pause before kill")
    set_kill_switch(True, "halt for test", settings=settings)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    kill = client.get("/api/ops/kill-switch").json()
    assert kill["engaged"] is True
    assert kill["reason"] == "halt for test"
    denied = client.post(
        f"/api/strategies/{STOCK_MOMENTUM_TOPK}/lifecycle",
        json={"action": "resume", "reason": "test"},
    )
    assert denied.status_code == 403
    detail = denied.json()["detail"]
    assert detail["code"] == "kill_switch"
    assert "急停" in detail["message"]
    assert "halt for test" in detail["message"]
    assert detail["kill_reason"] == "halt for test"
    set_kill_switch(False, "clear for other tests", settings=settings)


def test_p3_paper_run_rejects_duplicate_while_locked(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    token = acquire_paper_run_lock(settings, holder="test")
    with pytest.raises(PaperBusy, match="请勿重复提交"):
        run_paper_days(strategy_id=ETF_MA_ROTATE, days=5, settings=settings)
    with pytest.raises(PaperBusy, match="请勿重复提交"):
        reset_paper_account(strategy_id=ETF_MA_ROTATE, settings=settings)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    denied = client.post(
        "/api/paper/run",
        json={"strategy_id": ETF_MA_ROTATE, "days": 5, "background": False},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "paper_busy"
    release_paper_run_lock(settings, token)
    allowed = run_paper_days(strategy_id=ETF_MA_ROTATE, days=5, settings=settings)
    assert allowed["ok"] is True


def test_p3_quality_and_kill_reject_paper_orders(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    dates = sorted({row["trade_date"] for row in query_all("SELECT trade_date FROM trade_calendar", settings=settings)})
    fill = dates[-1]
    execute(
        """
        INSERT INTO quality_issue
            (issue_id, dataset, symbol, trade_date, check_type, severity, status, diff)
        VALUES ('p3-block', 'market_daily', '000001.SZ', ?, 'missing', 'block', 'open', 'p3')
        """,
        (fill,),
        settings=settings,
    )
    blocked = PaperOrderService(settings).build_orders(fill, STOCK_MOMENTUM_TOPK)
    assert blocked[0]["status"] == "rejected"
    assert "quality_block" in (blocked[0]["risk_tags"] or "")
    execute("UPDATE quality_issue SET status = 'closed' WHERE issue_id = 'p3-block'", settings=settings)
    set_kill_switch(True, "stop paper", settings=settings)
    killed = PaperOrderService(settings).build_orders(fill, STOCK_MOMENTUM_TOPK)
    assert killed[0]["status"] == "rejected"
    assert "kill_switch" in (killed[0]["risk_tags"] or "")
    set_kill_switch(False, "clear stop", settings=settings)


def test_p3_idempotent_orders_lot_and_t1(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    result = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert result["ok"] is True
    orders = query_all(
        "SELECT idem_key, COUNT(*) AS c FROM standard_order WHERE strategy_id = ? GROUP BY idem_key",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    assert orders
    assert all(int(row["c"]) == 1 for row in orders)
    lots = query_all(
        "SELECT quantity, status FROM standard_order WHERE strategy_id = ? AND symbol != '000000.SZ'",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    assert lots
    assert all(int(row["quantity"]) % 100 == 0 or row["status"] == "rejected" for row in lots)
    broker = PaperBroker(settings)
    assert broker.channel_status()["channel_id"] == "paper"


def test_p3_paper_cash_reconcile(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    from asqt.paper import paper_board

    board = paper_board(STOCK_MOMENTUM_TOPK, settings)
    rec = board["reconcile"]
    assert rec["ok"] is True
    assert abs(float(rec["cash_diff"])) <= 0.05
    assert rec["qty_mismatches"] == []
    assert rec["expected_cash"] == rec["actual_cash"] or abs(rec["cash_diff"]) <= 0.05
    cash_check = next(row for row in rec["checks"] if row["name"] == "现金")
    assert cash_check["ok"] is True
    qty_check = next(row for row in rec["checks"] if row["name"] == "持仓数量合计")
    assert qty_check["ok"] is True


def test_p3_reset_paper_account(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    from asqt.paper import paper_board, reset_paper_account

    before = paper_board(STOCK_MOMENTUM_TOPK, settings)
    assert before["summary"]["sessions"] >= 5
    cleared = reset_paper_account(strategy_id=STOCK_MOMENTUM_TOPK, settings=settings)
    assert cleared["ok"] is True
    assert cleared["reports"][0]["deleted_snapshots"] >= 5
    after = paper_board(STOCK_MOMENTUM_TOPK, settings)
    assert after["curve"] == []
    assert after["fills"] == []
    assert after["summary"]["sessions"] == 0
    # Empty/reset books are unfunded until the next run sets cash overrides.
    assert after["summary"]["initial_cash"] == 0.0
    assert after["summary"]["end_asset"] == 0.0
    leftover = query_all(
        "SELECT COUNT(*) AS c FROM standard_order WHERE strategy_id = ?",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )[0]["c"]
    assert int(leftover) == 0
    status = LocalStrategyService(settings).current_version(STOCK_MOMENTUM_TOPK)["status"]
    assert status == "paper"
    rerun = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert rerun["ok"] is True
    from asqt.paper import paper_board

    rec = paper_board(STOCK_MOMENTUM_TOPK, settings)["reconcile"]
    assert rec["ok"] is True
    assert rec["qty_mismatches"] == []


def test_reset_paper_clears_kill_switch(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=3, settings=settings)
    set_kill_switch(True, "engage before reset", settings=settings)
    assert kill_engaged(settings) is True
    from asqt.paper import reset_paper_account

    cleared = reset_paper_account(strategy_id=STOCK_MOMENTUM_TOPK, settings=settings)
    assert cleared["ok"] is True
    assert cleared["kill_switch"]["cleared"] is True
    assert cleared["kill_switch"]["engaged"] is False
    assert kill_engaged(settings) is False


def test_clear_strategy_halt_resumes_trading(tmp_path):
    from asqt.ops import LocalAlertService, set_paper_account_config
    from asqt.paper import PaperLedger, clear_strategy_halt, halt_status_of, paper_board

    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(False, "clear before resume halt test", settings=settings)
    set_paper_account_config(
        initial_cash=100_000,
        commission_per_myriad=2.5,
        portfolio_drawdown_stop_pct=50,
        strategy_drawdown_stop_pct=12,
        drawdown_warn_pct=8,
        settings=settings,
    )
    warm = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert warm["ok"] is True
    ledger = PaperLedger(STOCK_MOMENTUM_TOPK, settings)
    state = ledger.load()
    peak = float(state.get("peak_asset") or state.get("initial_cash") or 100_000)
    state["halted"] = True
    state["flatten_pending"] = bool(state.get("positions"))
    state["halt_reason"] = "strategy_drawdown"
    state["peak_asset"] = peak
    last = str(
        query_all(
            "SELECT trade_date FROM account_snapshot WHERE account_id = ? ORDER BY trade_date DESC LIMIT 1",
            (ledger.account_id,),
            settings=settings,
        )[0]["trade_date"]
    )
    marks = {
        symbol: float(item.get("market_price") or item.get("cost") or 0)
        for symbol, item in (state.get("positions") or {}).items()
    }
    ledger.save(last, state, marks)
    assert paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["halt_status"] in {
        "halted",
        "flatten_pending",
    }
    LocalAlertService(settings).raise_alert(
        "critical",
        "drawdown",
        "strategy drawdown halt",
        f'{{"strategy_id":"{STOCK_MOMENTUM_TOPK}","summary":"test halt"}}',
    )

    resumed = clear_strategy_halt(
        STOCK_MOMENTUM_TOPK,
        "operator resume after review",
        settings=settings,
    )
    assert resumed["ok"] is True
    assert resumed["changed"] is True
    assert resumed["halt_status"] == "active"
    after = ledger.load()
    assert after.get("halted") is False
    assert after.get("flatten_pending") is False
    board = paper_board(STOCK_MOMENTUM_TOPK, settings)
    assert board["summary"]["halt_status"] == "active"
    assert float(after.get("peak_asset") or 0) == pytest.approx(
        float(board["summary"]["end_asset"]),
        rel=1e-6,
    )
    open_alerts = LocalAlertService(settings).list_alerts(status="open")
    assert not any(
        row.get("title") in {"strategy drawdown halt", "flatten incomplete"}
        and STOCK_MOMENTUM_TOPK in str(row.get("detail") or "")
        for row in open_alerts
    )
    ledger.save(last, after, marks)
    assert halt_status_of(ledger.load()) == "active"


def test_strategy_halt_alerts_when_build_orders_sets_halt_before_save(tmp_path, monkeypatch):
    """Same-day flatten sets halted in-memory before ledger.save; first alert must still fire."""
    from asqt.ops import LocalAlertService, set_paper_account_config
    from asqt.paper import PaperLedger, paper_board

    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(False, "clear before halt-alert test", settings=settings)
    set_paper_account_config(
        initial_cash=100_000,
        commission_per_myriad=2.5,
        portfolio_drawdown_stop_pct=80,
        strategy_drawdown_stop_pct=10,
        drawdown_warn_pct=8,
        settings=settings,
    )
    warm = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert warm["ok"] is True

    posts: list[dict] = []

    def fake_post(row, **_kwargs):
        posts.append(dict(row))
        return {"channel": "feishu", "ok": True, "code": 0}

    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", fake_post)

    ledger = PaperLedger(STOCK_MOMENTUM_TOPK, settings)
    state = ledger.load()
    assert state.get("_prior_halted") is False
    last = str(
        query_all(
            "SELECT trade_date FROM account_snapshot WHERE account_id = ? ORDER BY trade_date DESC LIMIT 1",
            (ledger.account_id,),
            settings=settings,
        )[0]["trade_date"]
    )
    peak = float(state.get("peak_asset") or state.get("initial_cash") or 100_000)
    # Simulate build_orders same-day strategy stop: mark halted before save.
    state["peak_asset"] = peak
    state["cash"] = peak * 0.85
    state["positions"] = {}
    state["tradable"] = {}
    state["halted"] = True
    state["flatten_pending"] = False
    state["halt_reason"] = "strategy_drawdown"
    ledger.save(last, state, {})

    open_halts = [
        row
        for row in LocalAlertService(settings).list_alerts(status="open")
        if row.get("title") == "strategy drawdown halt"
        and STOCK_MOMENTUM_TOPK in str(row.get("detail") or "")
    ]
    assert len(open_halts) == 1
    assert any(p.get("title") == "strategy drawdown halt" for p in posts)
    assert paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["halt_status"] == "halted"

    # Reload + save again must not duplicate the open critical alert / Feishu push.
    posts.clear()
    again = ledger.load()
    assert again.get("_prior_halted") is True
    ledger.save(last, again, {})
    open_halts_after = [
        row
        for row in LocalAlertService(settings).list_alerts(status="open")
        if row.get("title") == "strategy drawdown halt"
        and STOCK_MOMENTUM_TOPK in str(row.get("detail") or "")
    ]
    assert len(open_halts_after) == 1
    assert not any(p.get("title") == "strategy drawdown halt" for p in posts)


def test_p3_paper_config_initial_cash_and_commission(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    from asqt.ops import paper_account_config, set_paper_account_config
    from asqt.paper import paper_board

    set_paper_account_config(initial_cash=500_000, commission_per_myriad=10, settings=settings)
    cfg = paper_account_config(settings)
    assert cfg["initial_cash"] == 500_000
    assert abs(cfg["commission_rate"] - 0.001) < 1e-12
    reset_paper_account(strategy_id=STOCK_MOMENTUM_TOPK, settings=settings)
    result = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert result["ok"] is True
    board = paper_board(STOCK_MOMENTUM_TOPK, settings)
    # Solo run of one selected strategy gets the full portfolio cash.
    assert board["summary"]["initial_cash"] == 500_000
    snap = query_all(
        "SELECT position_detail FROM account_snapshot WHERE account_id = ? ORDER BY trade_date LIMIT 1",
        (board["account_id"],),
        settings=settings,
    )
    assert float(json.loads(snap[0]["position_detail"])["initial_cash"]) == 500_000
    fills = query_all(
        """
        SELECT f.fee, f.filled_qty, f.filled_price
        FROM execution_fill f
        JOIN standard_order o ON o.order_id = f.order_id
        WHERE o.strategy_id = ? AND f.side = 'BUY'
        """,
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    assert fills
    sample = fills[0]
    notional = abs(float(sample["filled_qty"]) * float(sample["filled_price"]))
    expected = max(5.0, notional * 0.001)
    assert float(sample["fee"]) + 1e-6 >= expected


def test_solo_run_gets_full_portfolio_cash(tmp_path):
    from asqt.ops import set_paper_account_config
    from asqt.paper import paper_admitted_ids, paper_board

    settings, _engine, _service = _prepare(tmp_path)
    set_paper_account_config(initial_cash=100_000, commission_per_myriad=2.5, settings=settings)
    admitted = paper_admitted_ids(settings)
    assert admitted == [ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK]
    result = run_paper_days(strategy_id=ETF_MA_ROTATE, days=5, settings=settings)
    assert result["ok"] is True
    assert result["portfolio_cash"] == 100_000
    assert result["book_cash"] == [100_000.0]
    assert result["funding_universe"] == [ETF_MA_ROTATE]
    board = paper_board(ETF_MA_ROTATE, settings)
    assert board["summary"]["initial_cash"] == 100_000.0
    assert board["summary"]["end_asset"] == pytest.approx(100_000, rel=0.35)


def test_p3_twenty_day_run_ledger_fees_and_review(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    result = run_paper_days(strategy_id="all", days=20, settings=settings)
    assert result["ok"] is True
    assert result["days"] == 20
    from asqt.ops import paper_account_config
    from asqt.paper import split_parallel_cash

    portfolio = float(paper_account_config(settings)["initial_cash"])
    from asqt.paper import paper_admitted_ids

    expected = split_parallel_cash(portfolio, len(result["funding_universe"]))
    assert result["portfolio_cash"] == portfolio
    assert result["book_cash"] == expected
    assert result["funding_universe"] == paper_admitted_ids(settings)
    assert sum(expected) == portfolio
    for report, cash in zip(result["reports"], expected):
        assert report["snapshots"] >= 20
        assert report["last"]["total_asset"] > 0
        assert json.loads(report["last"]["position_detail"])["initial_cash"] == cash
    fills = query_all("SELECT filled_qty, filled_price, fee, side FROM execution_fill", settings=settings)
    assert fills
    assert all(float(row["fee"]) >= 0 for row in fills)
    sells = [row for row in fills if row["side"] == "SELL"]
    if sells:
        assert any(float(row["fee"]) >= 5 for row in sells)
    tasks = query_all("SELECT task_name, status FROM task_run WHERE task_name = 'paper-run'", settings=settings)
    assert tasks and tasks[0]["status"] == "success"
    review = LocalReviewService(settings).paper_vs_backtest(STOCK_MOMENTUM_TOPK)
    assert review["available"] is True
    assert review["items"][0]["n_days"] >= 20
    assert review["items"][0]["max_abs_nav_gap"] >= 0
    daily = LocalReviewService(settings).build_daily_review()
    assert daily["paper_vs_backtest"]["available"] is True


def test_sequential_multi_splits_portfolio_cash(tmp_path):
    from asqt.ops import set_paper_account_config
    from asqt.paper import paper_board

    settings, _engine, _service = _prepare(tmp_path)
    set_paper_account_config(initial_cash=100_000, commission_per_myriad=2.5, settings=settings)
    result = run_paper_days(
        strategy_ids=[ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK],
        days=5,
        settings=settings,
        mode="sequential",
    )
    assert result["ok"] is True
    assert result.get("mode") == "sequential"
    assert result["portfolio_cash"] == 100_000
    cash_a = paper_board(ETF_MA_ROTATE, settings)["summary"]["initial_cash"]
    cash_b = paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["initial_cash"]
    assert cash_a + cash_b == 100_000
    assert {cash_a, cash_b} == {50_000.0}
    end_a = paper_board(ETF_MA_ROTATE, settings)["summary"]["end_asset"]
    end_b = paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["end_asset"]
    # Combined NAV must stay near portfolio capital, not 2x.
    assert end_a + end_b == pytest.approx(100_000, rel=0.35)

def test_p3_alerts_dual_channel_and_api(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    alert = LocalAlertService(settings).raise_alert("high", "ops", "paper started", "p3")
    assert alert["alert_id"]
    local = (settings.logs_dir / "alerts.jsonl").read_text(encoding="utf-8")
    remote = (settings.logs_dir / "alerts_remote.jsonl").read_text(encoding="utf-8")
    assert "paper started" in local
    assert "paper started" in remote
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    ports = {item["name"]: item["status"] for item in client.get("/api/ports").json()}
    assert ports["ExecutionAdapter"] == "wired"
    assert ports["AlertService"] == "wired"
    kill = client.post("/api/ops/kill-switch", json={"engaged": True, "reason": "api halt"})
    assert kill.status_code == 200
    assert kill.json()["engaged"] is True
    assert kill_engaged(settings) is True
    resume = client.post("/api/ops/kill-switch", json={"engaged": False, "reason": "api resume"})
    assert resume.json()["engaged"] is False
    run = client.post(
        "/api/paper/run",
        json={"strategy_id": ETF_MA_ROTATE, "days": 5, "background": False},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "success"
    assert (body.get("detail") or {}).get("ok") is True
    account = client.get("/api/paper/account", params={"strategy_id": ETF_MA_ROTATE}).json()
    assert account["curve"]
    assert account["summary"]["sessions"] >= 5
    assert "total_return" in account["summary"]
    assert account["timeline"]
    listed = client.get("/api/alerts").json()
    assert listed
    attr = client.get("/api/research/attribution", params={"strategy_id": ETF_MA_ROTATE}).json()
    assert attr["paper_vs_backtest"]["available"] is True
    status = client.get("/api/status").json()
    assert status["kill_switch"] is False


def test_p3_suspended_name_rejected(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    dates = sorted({row["trade_date"] for row in query_all("SELECT DISTINCT trade_date FROM trade_calendar", settings=settings)})
    fill = dates[-1]
    signal = dates[-2]
    execute(
        """
        INSERT OR REPLACE INTO limit_suspension
            (symbol, trade_date, limit_up, limit_down, is_suspended, reason)
        VALUES ('510300.SH', ?, 4.5, 3.6, 1, 'halt')
        """,
        (fill,),
        settings=settings,
    )
    execute(
        """
        INSERT OR REPLACE INTO limit_suspension
            (symbol, trade_date, limit_up, limit_down, is_suspended, reason)
        VALUES ('510500.SH', ?, 4.5, 3.6, 1, 'halt')
        """,
        (fill,),
        settings=settings,
    )
    execute(
        """
        INSERT OR REPLACE INTO limit_suspension
            (symbol, trade_date, limit_up, limit_down, is_suspended, reason)
        VALUES ('159915.SZ', ?, 4.5, 3.6, 1, 'halt')
        """,
        (fill,),
        settings=settings,
    )
    created = PaperOrderService(settings).build_orders(fill, ETF_MA_ROTATE, signal_date=signal)
    buys = [row for row in created if row["side"] == "BUY" and row["symbol"] != "000000.SZ"]
    if buys:
        assert all(row["status"] == "rejected" for row in buys)
        assert all("suspended" in (row["risk_tags"] or "") for row in buys)


def test_paper_run_days_max_follows_calendar(tmp_path):
    from pydantic import ValidationError

    from asqt.api import PaperRunBody
    from asqt.paper import max_paper_run_days

    assert PaperRunBody(days=240).days == 240
    assert PaperRunBody(days=895).days == 895
    with pytest.raises(ValidationError):
        PaperRunBody(days=2001)
    assert PaperRunBody(mode="parallel").mode == "parallel"
    settings, _engine, _service = _prepare(tmp_path)
    assert max_paper_run_days(settings) >= 2


def test_split_parallel_cash_remainder_to_first():
    from asqt.paper import split_parallel_cash

    assert split_parallel_cash(100_000, 3) == [33334.0, 33333.0, 33333.0]
    assert split_parallel_cash(1_000_000, 2) == [500_000.0, 500_000.0]
    assert sum(split_parallel_cash(1_000_000, 5)) == 1_000_000


def test_parallel_mode_splits_cash_and_exposes_peak_return(tmp_path):
    from asqt.ops import set_paper_account_config
    from asqt.paper import paper_board

    settings, _engine, _service = _prepare(tmp_path)
    set_paper_account_config(initial_cash=100_000, commission_per_myriad=2.5, settings=settings)
    result = run_paper_days(
        strategy_ids=[ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK],
        days=5,
        settings=settings,
        mode="parallel",
    )
    assert result["ok"] is True
    assert result.get("mode") == "parallel"
    cash_a = paper_board(ETF_MA_ROTATE, settings)["summary"]["initial_cash"]
    cash_b = paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["initial_cash"]
    assert cash_a + cash_b == 100_000
    assert {cash_a, cash_b} == {50_000.0}
    board = paper_board(STOCK_MOMENTUM_TOPK, settings)
    assert "peak_return" in board["summary"]
    assert board["summary"]["peak_return"] == pytest.approx(
        board["summary"]["peak_asset"] / board["summary"]["initial_cash"] - 1.0
    )
    assert "peak_return" in board["reconcile"]
    assert board["reconcile"]["peak_return"] == pytest.approx(board["summary"]["peak_return"])


def test_parallel_mode_kill_halts_sibling_strategies(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(False, "ensure off before mid-run kill", settings=settings)
    original = PaperOrderService.build_orders
    calls = {"n": 0}

    def wrapped(self, *args, **kwargs):
        out = original(self, *args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1 and not kill_engaged(settings):
            set_kill_switch(True, "mid parallel kill", settings=settings)
        return out

    monkeypatch.setattr(PaperOrderService, "build_orders", wrapped)
    result = run_paper_days(
        strategy_ids=[ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK],
        days=8,
        settings=settings,
        mode="parallel",
    )
    assert result["ok"] is False
    assert "kill_switch" in result["incomplete_reasons"]
    assert len(result["reports"]) == 2
    assert all(item.get("incomplete_reason") == "kill_switch" for item in result["reports"])
    # After portfolio kill, remaining days still liquidate/cash-mark so counts stay aligned.
    snaps = [int(item.get("snapshots") or 0) for item in result["reports"]]
    assert snaps[0] == snaps[1] == 8
    set_kill_switch(False, "clear after parallel kill test", settings=settings)


def test_parallel_mode_keeps_snapshot_dates_aligned(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(False, "ensure off before alignment test", settings=settings)
    original = PaperOrderService.build_orders
    calls = {"n": 0}

    def wrapped(self, *args, **kwargs):
        out = original(self, *args, **kwargs)
        calls["n"] += 1
        # Engage kill after both strategies finish session 1 (day-aligned fan-out).
        if calls["n"] == 2 and not kill_engaged(settings):
            set_kill_switch(True, "aligned parallel kill", settings=settings)
        return out

    monkeypatch.setattr(PaperOrderService, "build_orders", wrapped)
    result = run_paper_days(
        strategy_ids=[ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK],
        days=6,
        settings=settings,
        mode="parallel",
    )
    snaps = [int(item.get("snapshots") or 0) for item in result["reports"]]
    assert snaps[0] == snaps[1] == 6
    dates = []
    for sid in (ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK):
        rows = query_all(
            "SELECT trade_date FROM account_snapshot WHERE account_id = ? ORDER BY trade_date",
            (account_id_for(sid),),
            settings=settings,
        )
        dates.append([row["trade_date"] for row in rows])
    assert dates[0] == dates[1]
    assert len(dates[0]) == 6
    set_kill_switch(False, "clear after alignment test", settings=settings)


def test_parallel_mode_preengaged_kill_skips_all(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(True, "pre-engage for parallel kill test", settings=settings)
    result = run_paper_days(
        strategy_ids=[ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK],
        days=5,
        settings=settings,
        mode="parallel",
    )
    assert result["ok"] is False
    assert "kill_switch" in result["incomplete_reasons"]
    assert len(result["reports"]) == 2
    assert all(item.get("incomplete_reason") == "kill_switch" for item in result["reports"])
    assert all(int(item.get("snapshots") or 0) == 0 for item in result["reports"])
    set_kill_switch(False, "clear after parallel kill test", settings=settings)


def test_strategy_halt_flattens_without_global_kill(tmp_path):
    from asqt.ops import set_paper_account_config
    from asqt.paper import PaperLedger, PaperOrderService, account_id_for, paper_board
    from asqt.storage import read_market_daily

    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(False, "clear before strategy halt test", settings=settings)
    set_paper_account_config(
        initial_cash=100_000,
        commission_per_myriad=2.5,
        portfolio_drawdown_stop_pct=50,
        strategy_drawdown_stop_pct=12,
        drawdown_warn_pct=8,
        settings=settings,
    )
    warm = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert warm["ok"] is True
    ledger = PaperLedger(STOCK_MOMENTUM_TOPK, settings)
    state = ledger.load()
    assert state["positions"], "need holdings before flatten test"
    last = str(
        query_all(
            "SELECT trade_date FROM account_snapshot WHERE account_id = ? ORDER BY trade_date DESC LIMIT 1",
            (account_id_for(STOCK_MOMENTUM_TOPK),),
            settings=settings,
        )[0]["trade_date"]
    )
    execute(
        "DELETE FROM execution_fill WHERE order_id IN (SELECT order_id FROM standard_order WHERE strategy_id = ? AND trade_date = ? AND side = 'SELL')",
        (STOCK_MOMENTUM_TOPK, last),
        settings=settings,
    )
    execute(
        "DELETE FROM standard_order WHERE strategy_id = ? AND trade_date = ? AND side = 'SELL'",
        (STOCK_MOMENTUM_TOPK, last),
        settings=settings,
    )
    fees_before = float(paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"].get("fees") or 0)
    rows = read_market_daily(end=last, settings=settings)
    by_key = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
    state["tradable"] = {symbol: int(item["qty"]) for symbol, item in state["positions"].items()}
    state["halted"] = True
    state["flatten_pending"] = True
    state["halt_reason"] = "strategy_drawdown"
    service = PaperOrderService(settings)
    created = service._flatten_all(
        state=state,
        trade_date=last,
        strategy_id=STOCK_MOMENTUM_TOPK,
        by_key=by_key,
        risk_tag="strategy_halt",
        apply_fills=True,
    )
    marks = {
        symbol: float(by_key[(last, symbol)]["close"])
        for symbol in state["positions"]
        if (last, symbol) in by_key
    }
    ledger.save(last, state, marks)
    assert kill_engaged(settings) is False
    assert any(item.get("side") == "SELL" and item.get("status") == "filled" for item in created)
    assert any("strategy_halt" in str(item.get("risk_tags") or "") for item in created)
    after = ledger.load()
    assert after.get("halted") is True
    assert after.get("flatten_pending") is False
    assert after.get("positions") == {}
    board = paper_board(STOCK_MOMENTUM_TOPK, settings)
    assert board["summary"]["halt_status"] == "halted"
    fees_after = float(board["summary"].get("fees") or 0)
    assert fees_after > fees_before
    sibling = run_paper_days(strategy_id=ETF_MA_ROTATE, days=3, settings=settings)
    assert sibling["ok"] is True
    assert kill_engaged(settings) is False


def test_flatten_pending_retries_next_day_and_alerts(tmp_path, monkeypatch):
    import json

    from asqt.ops import LocalAlertService, set_paper_account_config
    from asqt.paper import (
        PaperLedger,
        PaperOrderService,
        _set_cash_override,
        account_id_for,
        paper_board,
    )
    from asqt.storage import read_market_daily

    settings, _engine, _service = _prepare(tmp_path)
    set_kill_switch(False, "clear before flatten pending test", settings=settings)
    set_paper_account_config(
        initial_cash=100_000,
        commission_per_myriad=2.5,
        portfolio_drawdown_stop_pct=50,
        strategy_drawdown_stop_pct=12,
        drawdown_warn_pct=8,
        settings=settings,
    )
    # Direct build_orders bypasses run_paper_days funding; seed book cash like a solo run.
    _set_cash_override(settings, STOCK_MOMENTUM_TOPK, 100_000.0)
    dates = sorted({str(row["trade_date"]) for row in read_market_daily(settings=settings)})
    service = PaperOrderService(settings)
    # Leave headroom at the end of the calendar for reject + retry days.
    for index in range(len(dates) - 8, len(dates) - 3):
        service.build_orders(dates[index], STOCK_MOMENTUM_TOPK, signal_date=dates[index - 1], apply_fills=True)
    hold_day = dates[len(dates) - 4]
    reject_day = dates[len(dates) - 3]
    retry_day = dates[len(dates) - 2]
    ledger = PaperLedger(STOCK_MOMENTUM_TOPK, settings)
    state = ledger.load()
    assert state["positions"], "need holdings before pending flatten"
    hold_row = query_all(
        "SELECT position_detail FROM account_snapshot WHERE account_id = ? AND trade_date = ?",
        (account_id_for(STOCK_MOMENTUM_TOPK), hold_day),
        settings=settings,
    )[0]
    detail = json.loads(hold_row["position_detail"] or "{}")
    detail["halted"] = True
    detail["flatten_pending"] = True
    detail["halt_reason"] = "strategy_drawdown"
    execute(
        "UPDATE account_snapshot SET position_detail = ? WHERE account_id = ? AND trade_date = ?",
        (json.dumps(detail, ensure_ascii=False), account_id_for(STOCK_MOMENTUM_TOPK), hold_day),
        settings=settings,
    )
    # Drop sessions after hold_day so reject_day starts from halted holdings.
    execute(
        "DELETE FROM execution_fill WHERE order_id IN (SELECT order_id FROM standard_order WHERE strategy_id = ? AND trade_date > ?)",
        (STOCK_MOMENTUM_TOPK, hold_day),
        settings=settings,
    )
    execute(
        "DELETE FROM standard_order WHERE strategy_id = ? AND trade_date > ?",
        (STOCK_MOMENTUM_TOPK, hold_day),
        settings=settings,
    )
    execute(
        "DELETE FROM account_snapshot WHERE account_id = ? AND trade_date > ?",
        (account_id_for(STOCK_MOMENTUM_TOPK), hold_day),
        settings=settings,
    )

    original_match = PaperOrderService._match

    def reject_sells(self, order, state, bar, trade_date):
        if order.get("side") == "SELL":
            execute(
                "UPDATE standard_order SET status = 'rejected', risk_tags = ?, updated_at = ? WHERE order_id = ?",
                ("strategy_halt,limit_down", "2024-01-01T00:00:00+00:00", order["order_id"]),
                settings=settings,
            )
            order["status"] = "rejected"
            order["risk_tags"] = "strategy_halt,limit_down"
            return
        return original_match(self, order, state, bar, trade_date)

    monkeypatch.setattr(PaperOrderService, "_match", reject_sells)
    blocked = service.build_orders(reject_day, STOCK_MOMENTUM_TOPK, signal_date=hold_day, apply_fills=True)
    assert any(item.get("side") == "SELL" for item in blocked)
    pending = ledger.load()
    assert pending.get("flatten_pending") is True
    assert pending.get("positions")
    assert paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["halt_status"] == "flatten_pending"
    alerts = LocalAlertService(settings).list_alerts(status="open")
    assert any(row.get("title") == "flatten incomplete" for row in alerts)

    monkeypatch.setattr(PaperOrderService, "_match", original_match)
    done = service.build_orders(retry_day, STOCK_MOMENTUM_TOPK, signal_date=reject_day, apply_fills=True)
    assert any(item.get("side") == "SELL" and item.get("status") == "filled" for item in done)
    final = ledger.load()
    assert final.get("halted") is True
    assert final.get("flatten_pending") is False
    assert final.get("positions") == {}
    assert paper_board(STOCK_MOMENTUM_TOPK, settings)["summary"]["halt_status"] == "halted"
    open_alerts = LocalAlertService(settings).list_alerts(status="open")
    assert not any(
        row.get("title") == "flatten incomplete" and STOCK_MOMENTUM_TOPK in str(row.get("detail") or "")
        for row in open_alerts
    )


def test_paper_config_rejects_initial_cash_below_minimum(tmp_path):
    from asqt.ops import set_paper_account_config

    settings, _engine, _service = _prepare(tmp_path)
    with pytest.raises(ValueError, match="初始资金需在 10,000"):
        set_paper_account_config(initial_cash=9_999, commission_per_myriad=3.0, settings=settings)
    ok = set_paper_account_config(initial_cash=10_000, commission_per_myriad=3.0, settings=settings)
    assert ok["initial_cash"] == 10_000


def test_paper_config_drawdown_thresholds_roundtrip(tmp_path):
    from asqt.ops import paper_account_config, set_paper_account_config

    settings, _engine, _service = _prepare(tmp_path)
    after = set_paper_account_config(
        initial_cash=200_000,
        commission_per_myriad=3.0,
        portfolio_drawdown_stop_pct=15,
        strategy_drawdown_stop_pct=10,
        drawdown_warn_pct=6,
        settings=settings,
    )
    assert after["portfolio_drawdown_stop_pct"] == 15
    assert after["strategy_drawdown_stop_pct"] == 10
    assert after["drawdown_warn_pct"] == 6
    loaded = paper_account_config(settings)
    assert loaded["portfolio_drawdown_stop"] == pytest.approx(0.15)
    assert loaded["strategy_drawdown_stop"] == pytest.approx(0.10)
    assert loaded["drawdown_warn"] == pytest.approx(0.06)


def test_drawdown_warn_is_per_strategy_not_global(tmp_path, monkeypatch):
    from asqt.ops import LocalAlertService, maybe_drawdown_halt, set_paper_account_config

    settings, _engine, _service = _prepare(tmp_path)
    set_paper_account_config(
        initial_cash=100_000,
        commission_per_myriad=2.5,
        portfolio_drawdown_stop_pct=50,
        strategy_drawdown_stop_pct=30,
        drawdown_warn_pct=8,
        settings=settings,
    )
    posts: list[dict] = []

    def fake_post(row, **_kwargs):
        posts.append(row)
        return {"channel": "feishu", "ok": True, "code": 0}

    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", fake_post)

    first = maybe_drawdown_halt(
        peak=100_000,
        total_asset=91_000,
        initial_cash=50_000,
        strategy_id=ETF_MA_ROTATE,
        account_id=f"paper:{ETF_MA_ROTATE}",
        trade_date="2024-06-01",
        settings=settings,
    )
    second = maybe_drawdown_halt(
        peak=100_000,
        total_asset=90_000,
        initial_cash=50_000,
        strategy_id=STOCK_MOMENTUM_TOPK,
        account_id=f"paper:{STOCK_MOMENTUM_TOPK}",
        trade_date="2024-06-01",
        settings=settings,
    )
    assert first["dd"] <= -0.08
    assert second["dd"] <= -0.08
    open_rows = LocalAlertService(settings).list_alerts(status="open")
    warns = [
        row
        for row in open_rows
        if row.get("title") == "max drawdown warning" and row.get("category") == "drawdown"
    ]
    assert len(warns) == 2
    details = " ".join(str(row.get("detail") or "") for row in warns)
    assert ETF_MA_ROTATE in details
    assert STOCK_MOMENTUM_TOPK in details
    assert len(posts) >= 2
