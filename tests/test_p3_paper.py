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


def test_p3_paper_config_initial_cash_and_commission(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    from asqt.ops import paper_account_config, set_paper_account_config
    from asqt.paper import paper_board, reset_paper_account

    set_paper_account_config(initial_cash=500_000, commission_per_myriad=10, settings=settings)
    cfg = paper_account_config(settings)
    assert cfg["initial_cash"] == 500_000
    assert abs(cfg["commission_rate"] - 0.001) < 1e-12
    reset_paper_account(strategy_id=STOCK_MOMENTUM_TOPK, settings=settings)
    result = run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    assert result["ok"] is True
    board = paper_board(STOCK_MOMENTUM_TOPK, settings)
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


def test_p3_twenty_day_run_ledger_fees_and_review(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    result = run_paper_days(strategy_id="all", days=20, settings=settings)
    assert result["ok"] is True
    assert result["days"] == 20
    for report in result["reports"]:
        assert report["snapshots"] >= 20
        assert report["last"]["total_asset"] > 0
        assert json.loads(report["last"]["position_detail"])["initial_cash"] == 1_000_000
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


def test_paper_run_days_max_is_240():
    from pydantic import ValidationError

    from asqt.api import PaperRunBody

    assert PaperRunBody(days=240).days == 240
    with pytest.raises(ValidationError):
        PaperRunBody(days=241)
