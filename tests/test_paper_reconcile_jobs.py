from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from asqt.db import execute, query_all
from asqt.paper import account_id_for, run_paper_days
from asqt.paper_reconcile_jobs import (
    CASH_RECONCILE_HOUR,
    CASH_RECONCILE_MINUTE,
    paper_overview_metrics,
    run_cash_reconcile_job,
    should_auto_cash_reconcile,
    _validate_paper_overview,
)
from asqt.strategies import STOCK_MOMENTUM_TOPK
from tests.test_p3_paper import _prepare


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_run_cash_reconcile_job_pass(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    captured = {}

    def fake_post(row, **_kwargs):
        captured["row"] = row
        return {"channel": "feishu", "ok": True, "code": 0}

    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", fake_post)
    report = run_cash_reconcile_job(
        trigger="manual",
        settings=settings,
        notify=True,
        strategy_ids=[STOCK_MOMENTUM_TOPK],
    )
    assert report["task_status"] == "success"
    assert report["ok"] is True
    assert report["checked"] == 1
    assert report["mismatch_count"] == 0
    assert report["portfolio"]["ok"] is True
    assert report["books"][0]["expected_share"] is not None
    tasks = query_all(
        "SELECT * FROM task_run WHERE task_name = 'cash-reconcile' ORDER BY created_at DESC",
        settings=settings,
    )
    assert tasks and tasks[0]["status"] == "success"
    alerts = query_all(
        "SELECT * FROM alert WHERE category = 'cash_reconcile' AND status = 'open'",
        settings=settings,
    )
    assert alerts and alerts[0]["title"] == "财务对账通过"
    detail = json.loads(alerts[0]["detail"])
    assert detail["kind"] == "cash_reconcile"
    assert "财务对账通过" in detail["summary"]
    assert "portfolio" in detail
    assert captured.get("row", {}).get("level") == "high"


def test_run_cash_reconcile_job_partial_on_cash_tamper(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    run_paper_days(strategy_id=STOCK_MOMENTUM_TOPK, days=5, settings=settings)
    account_id = account_id_for(STOCK_MOMENTUM_TOPK)
    latest = query_all(
        """
        SELECT trade_date, cash FROM account_snapshot
        WHERE account_id = ? ORDER BY trade_date DESC LIMIT 1
        """,
        (account_id,),
        settings=settings,
    )[0]
    execute(
        "UPDATE account_snapshot SET cash = ? WHERE account_id = ? AND trade_date = ?",
        (float(latest["cash"]) - 1234.56, account_id, latest["trade_date"]),
        settings=settings,
    )
    captured = {}

    def fake_post(row, **_kwargs):
        captured["row"] = row
        return {"channel": "feishu", "ok": True, "code": 0}

    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", fake_post)
    report = run_cash_reconcile_job(
        trigger="manual",
        settings=settings,
        notify=True,
        strategy_ids=[STOCK_MOMENTUM_TOPK],
    )
    assert report["task_status"] == "partial"
    assert report["ok"] is False
    assert report["mismatch_count"] >= 1
    book = next(item for item in report["books"] if item["strategy_id"] == STOCK_MOMENTUM_TOPK)
    assert book["ok"] is False
    assert "现金" in (book.get("failed_checks") or [])
    alerts = query_all(
        "SELECT title, detail FROM alert WHERE category='cash_reconcile' AND status='open'",
        settings=settings,
    )
    assert alerts and alerts[0]["title"] == "财务对账不一致"
    detail = json.loads(alerts[0]["detail"])
    assert detail["mismatch_count"] >= 1
    assert any(not item.get("ok") for item in detail["books"] if not item.get("skipped"))
    assert captured.get("row", {}).get("level") == "high"


def test_run_cash_reconcile_job_skips_empty_books(tmp_path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    # Admit only — no paper sessions yet.
    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", lambda *_a, **_k: {"ok": True})
    report = run_cash_reconcile_job(
        trigger="manual",
        settings=settings,
        notify=True,
        strategy_ids=[STOCK_MOMENTUM_TOPK],
    )
    assert report["task_status"] == "success"
    assert report["checked"] == 0
    assert report["skipped_count"] == 1
    assert report["books"][0]["skipped"] is True
    assert report["books"][0]["reason"] == "尚无账本"
    alerts = query_all(
        "SELECT title, detail FROM alert WHERE category='cash_reconcile' AND status='open'",
        settings=settings,
    )
    assert alerts and alerts[0]["title"] == "财务对账跳过"
    detail = json.loads(alerts[0]["detail"])
    assert "无可用账本" in detail["summary"] or "尚无账本" in detail["summary"]
    assert "跑模拟" in detail["action"]


def test_run_cash_reconcile_job_skips_when_inflight(tmp_path):
    from asqt.db import initialize_database

    settings, _engine, _service = _prepare(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES ('c1', 'cash-reconcile', 'running', '2099-01-01T00:00:00+00:00', NULL, 'hold')
        """,
        settings=settings,
    )
    result = run_cash_reconcile_job(
        trigger="auto",
        settings=settings,
        notify=False,
        strategy_ids=[STOCK_MOMENTUM_TOPK],
    )
    assert result.get("skipped") is True
    assert result.get("reason") == "inflight"


def test_should_auto_cash_reconcile_respects_window(tmp_path, monkeypatch):
    from asqt.db import initialize_database

    settings, _engine, _service = _prepare(tmp_path)
    initialize_database(settings)
    monkeypatch.setenv("ASQT_CASH_RECONCILE_AUTO", "1")
    fixed = datetime(2026, 9, 11, CASH_RECONCILE_HOUR, CASH_RECONCILE_MINUTE, tzinfo=SHANGHAI)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr("asqt.paper_reconcile_jobs.datetime", _FixedDateTime)
    monkeypatch.setattr("asqt.paper_reconcile_jobs.auto_cash_reconcile_enabled", lambda: True)
    assert should_auto_cash_reconcile(settings) is True


def test_run_cash_reconcile_detects_full_cash_not_shared(tmp_path, monkeypatch):
    """Legacy full-cash books among multi-admitted strategies should fail funding checks."""
    from asqt.ops import set_paper_account_config
    from asqt.paper import account_id_for
    from asqt.strategies import ETF_MA_ROTATE

    settings, _engine, _service = _prepare(tmp_path)
    set_paper_account_config(initial_cash=100_000, commission_per_myriad=2.5, settings=settings)
    # Multi-run first so each book is a fair share; then inflate one to full cash.
    run_paper_days(
        strategy_ids=[STOCK_MOMENTUM_TOPK, ETF_MA_ROTATE],
        days=5,
        settings=settings,
        mode="sequential",
    )
    account_id = account_id_for(STOCK_MOMENTUM_TOPK)
    rows = query_all(
        "SELECT trade_date, position_detail FROM account_snapshot WHERE account_id = ?",
        (account_id,),
        settings=settings,
    )
    for row in rows:
        detail = json.loads(row["position_detail"] or "{}")
        detail["initial_cash"] = 100_000.0
        detail["peak_asset"] = max(float(detail.get("peak_asset") or 0), 100_000.0)
        execute(
            "UPDATE account_snapshot SET position_detail = ? WHERE account_id = ? AND trade_date = ?",
            (json.dumps(detail, ensure_ascii=False), account_id, row["trade_date"]),
            settings=settings,
        )
    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", lambda *_a, **_k: {"ok": True})
    report = run_cash_reconcile_job(
        trigger="manual",
        settings=settings,
        notify=True,
        strategy_ids=[STOCK_MOMENTUM_TOPK, ETF_MA_ROTATE],
    )
    assert report["task_status"] == "partial"
    assert report["ok"] is False
    book = next(item for item in report["books"] if item["strategy_id"] == STOCK_MOMENTUM_TOPK)
    assert book["ok"] is False
    assert "本金份额" in (book.get("failed_checks") or []) or "本金未均分" in (book.get("failed_checks") or [])
    detail = json.loads(
        query_all(
            "SELECT detail FROM alert WHERE category='cash_reconcile' AND status='open'",
            settings=settings,
        )[0]["detail"]
    )
    assert detail["portfolio"]["portfolio_cash"] == 100_000


def test_cash_reconcile_alert_format_lines():
    from asqt.alert_format import encode_alert_detail, format_alert_full, format_feishu_text

    payload = {
        "schema": "asqt.alert.v1",
        "kind": "cash_reconcile",
        "summary": "财务对账不一致 · 1/1（股票动量 TopK）",
        "trigger": "manual",
        "checked": 1,
        "mismatch_count": 1,
        "skipped_count": 0,
        "books": [
            {
                "strategy_id": STOCK_MOMENTUM_TOPK,
                "strategy_label": "股票动量 TopK",
                "skipped": False,
                "ok": False,
                "asof": "2024-01-10",
                "initial_cash": 1_000_000,
                "peak_asset": 1_010_000,
                "actual_cash": 100_000,
                "expected_cash": 101_234.56,
                "cash_diff": -1234.56,
                "market_value": 900_000,
                "end_asset": 1_000_000,
                "qty_mismatches": 0,
                "failed_checks": ["现金", "总资产"],
            }
        ],
        "action": "请到交易页「财务对账」核对不一致账本；不一致不自动急停。",
        "portfolio": {
            "ok": False,
            "portfolio_cash": 100_000,
            "deployed": 1_000_000,
            "nav": 1_000_000,
            "failed_checks": ["组合本金合计"],
        },
    }
    row = {
        "level": "high",
        "category": "cash_reconcile",
        "title": "财务对账不一致",
        "detail": encode_alert_detail(payload),
    }
    full = format_alert_full(row)
    feishu = format_feishu_text(row)
    assert "类别：财务对账" in full
    assert "现金差额" in full or "差额" in full
    assert "组合资金" in full
    assert "处置：" in full
    assert "【ASQT告警】重要 · 财务对账" in feishu
    assert "/Users/" not in feishu


def test_paper_overview_metrics_uses_deployed_not_setting_when_underfunded():
    """Reproduce UI bug: 2×12.5k books must not show -76% vs 100k setting cash."""
    books = [
        {
            "strategy_id": "etf_ma_rotate",
            "initial_cash": 12_500.0,
            "end_asset": 11_590.9594,
            "cash": 11_590.9594,
            "market_value": 0.0,
            "peak_asset": 12_919.7993,
        },
        {
            "strategy_id": "stock_momentum_topk",
            "initial_cash": 12_500.0,
            "end_asset": 11_875.9453,
            "cash": 11_875.9453,
            "market_value": 0.0,
            "peak_asset": 12_556.1758,
        },
    ]
    overview = paper_overview_metrics(books, portfolio_cash=100_000.0)
    assert overview["underfunded"] is True
    assert overview["principal"] == 25_000.0
    assert abs(overview["nav"] - 23_466.9047) < 1e-4
    # Wrong old UI: 23466/100000-1 ≈ -76.5%; correct ≈ -6.1%.
    assert overview["total_return"] > -0.1
    assert overview["total_return"] < 0
    assert abs(overview["total_return"] - (overview["nav"] / 25_000.0 - 1)) < 1e-9
    checked = _validate_paper_overview(books=books, portfolio_cash=100_000.0)
    assert checked["ok"] is True
    assert "账户总览本金口径" not in checked["failed_checks"]


def test_paper_overview_metrics_scales_when_overfunded():
    books = [
        {
            "strategy_id": "lab",
            "initial_cash": 100_000.0,
            "end_asset": 90_000.0,
            "cash": 90_000.0,
            "market_value": 0.0,
            "peak_asset": 105_000.0,
        },
        {
            "strategy_id": "other",
            "initial_cash": 12_500.0,
            "end_asset": 12_000.0,
            "cash": 12_000.0,
            "market_value": 0.0,
            "peak_asset": 12_500.0,
        },
    ]
    overview = paper_overview_metrics(books, portfolio_cash=100_000.0)
    assert overview["overfunded"] is True
    assert overview["principal"] == 100_000.0
    assert abs(overview["nav"] - (102_000.0 * 100_000.0 / 112_500.0)) < 0.02
    checked = _validate_paper_overview(books=books, portfolio_cash=100_000.0)
    assert checked["ok"] is True


def test_paper_overview_metrics_reads_summary_cash_from_book_payload():
    books = [
        {
            "strategy_id": "lab",
            "initial_cash": 12_500.0,
            "end_asset": 12_500.0,
            "cash": 8_000.0,
            "actual_cash": 0.0,
            "market_value": 4_500.0,
            "peak_asset": 12_500.0,
        }
    ]
    overview = paper_overview_metrics(books, portfolio_cash=100_000.0)
    assert overview["cash"] == 8_000.0
    checked = _validate_paper_overview(books=books, portfolio_cash=100_000.0)
    assert "账户总览净资产恒等式" not in checked["failed_checks"]
