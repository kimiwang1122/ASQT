from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from asqt.db import query_all
from asqt.reconcile_jobs import (
    RECONCILE_HOUR,
    RECONCILE_MINUTE,
    run_reconcile_job,
    should_auto_reconcile,
)
from asqt.pipeline import pull_daily
from tests.test_p1_data import FakeAdapter, _bar
from tests.test_sync import make_settings


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _seed(settings):
    adapter = FakeAdapter(
        [
            _bar("000001.SZ", "2024-01-02"),
            _bar("000001.SZ", "2024-01-03"),
        ]
    )
    adapter.calendar = [
        {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
        {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
    ]
    pull_daily(["000001.SZ"], "2024-01-02", "2024-01-03", settings=settings, adapter=adapter)
    return adapter


def test_run_reconcile_job_writes_task_and_feishu_alert(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    peer = _seed(settings)

    captured = {}

    def fake_post(row, **_kwargs):
        captured["row"] = row
        return {"channel": "feishu", "ok": True, "code": 0}

    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", fake_post)
    monkeypatch.setattr(
        "asqt.pipeline.build_adapter",
        lambda source_id: peer,
    )

    report = run_reconcile_job(
        trigger="auto",
        lookback_days=14,
        peer_source="baostock",
        settings=settings,
        symbols=["000001.SZ"],
        notify=True,
    )
    assert report["task_status"] in {"success", "partial"}
    tasks = query_all(
        "SELECT * FROM task_run WHERE task_name = 'reconcile-daily' ORDER BY created_at DESC",
        settings=settings,
    )
    assert tasks
    assert "匹配" in (tasks[0]["message"] or "")
    alerts = query_all(
        "SELECT * FROM alert WHERE category = 'reconcile' AND status = 'open'",
        settings=settings,
    )
    assert alerts
    detail = json.loads(alerts[0]["detail"])
    assert detail["kind"] == "cross_source_reconcile"
    assert "summary" in detail
    assert captured.get("row", {}).get("level") == "high"


def test_should_auto_reconcile_respects_window(tmp_path, monkeypatch):
    from asqt.db import initialize_database

    settings = make_settings(tmp_path)
    initialize_database(settings)
    monkeypatch.setenv("ASQT_RECONCILE_AUTO", "1")
    # Force a weekday after the reconcile window.
    fixed = datetime(2026, 9, 11, RECONCILE_HOUR, RECONCILE_MINUTE, tzinfo=SHANGHAI)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr("asqt.reconcile_jobs.datetime", _FixedDateTime)
    monkeypatch.setattr("asqt.reconcile_jobs.auto_reconcile_enabled", lambda: True)
    assert should_auto_reconcile(settings) is True


def test_choose_auto_peer_prefers_tushare(monkeypatch):
    from asqt.pipeline import choose_auto_peer

    monkeypatch.setattr("asqt.pipeline.tushare_peer_available", lambda: True)
    assert choose_auto_peer({"baostock"}) == "tushare"
    monkeypatch.setattr("asqt.pipeline.tushare_peer_available", lambda: False)
    assert choose_auto_peer({"baostock"}) == "akshare"
    assert choose_auto_peer({"akshare"}) == "baostock"


def test_run_reconcile_job_timeout_marks_failed_and_notifies(tmp_path, monkeypatch):
    from asqt.db import initialize_database
    from asqt.reconcile_jobs import run_reconcile_job

    settings = make_settings(tmp_path)
    initialize_database(settings)
    captured: dict = {}

    def fake_post(row, **_kwargs):
        captured["row"] = row
        return {"channel": "feishu", "ok": True, "code": 0}

    def slow_reconcile(*_args, **_kwargs):
        import time

        time.sleep(2)
        return {}

    monkeypatch.setattr("asqt.adapters.feishu_alert.post_feishu_alert", fake_post)
    monkeypatch.setattr("asqt.pipeline.reconcile_daily", slow_reconcile)
    monkeypatch.setattr("asqt.reconcile_jobs.poc_symbols", lambda _settings=None: ["000001.SZ"])

    result = run_reconcile_job(
        trigger="manual",
        settings=settings,
        notify=True,
        timeout_s=0.3,
        symbols=["000001.SZ"],
    )
    assert result.get("timed_out") is True
    assert result.get("task_status") == "failed"
    tasks = query_all(
        "SELECT status, message FROM task_run WHERE task_name='reconcile-daily' ORDER BY created_at DESC LIMIT 1",
        settings=settings,
    )
    assert tasks[0]["status"] == "failed"
    assert "超时" in (tasks[0]["message"] or "")
    alerts = query_all(
        "SELECT title, detail FROM alert WHERE category='reconcile' AND status='open'",
        settings=settings,
    )
    assert alerts and alerts[0]["title"] == "跨源对账失败"
    assert captured.get("row", {}).get("level") == "high"


def test_run_reconcile_job_skips_when_inflight(tmp_path):
    from asqt.db import execute, initialize_database
    from asqt.reconcile_jobs import run_reconcile_job

    settings = make_settings(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES ('r1', 'reconcile-daily', 'running', '2099-01-01T00:00:00+00:00', NULL, 'hold')
        """,
        settings=settings,
    )
    result = run_reconcile_job(trigger="auto", settings=settings, notify=False, symbols=["000001.SZ"])
    assert result.get("skipped") is True
    assert result.get("reason") == "inflight"
