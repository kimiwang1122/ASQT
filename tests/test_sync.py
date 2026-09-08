from __future__ import annotations

from pathlib import Path
import threading

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.config import Settings
from asqt.db import execute, initialize_database, query_all
from asqt.pipeline import pull_daily
from asqt.storage import read_market_daily
from asqt.sync import (
    Busy,
    SYNC_LOCK_ID,
    abort_inflight_sync_runs,
    get_sync_run,
    list_sync_runs,
    recover_orphaned_sync_runs,
    run_sync_job,
    should_auto_run,
    start_sync_job,
    vendor_asof_ready,
)
from tests.test_p1_data import FakeAdapter, _bar


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "asqt.sqlite3",
        parquet_dir=tmp_path / "data" / "parquet",
        raw_dir=tmp_path / "data" / "raw_data",
        standard_dir=tmp_path / "data" / "standard_data",
        qlib_dir=tmp_path / "data" / "qlib_data",
        experiment_dir=tmp_path / "data" / "experiment",
        logs_dir=tmp_path / "data" / "logs",
        frontend_dir=tmp_path / "frontend",
    )


def _seed_bars(settings: Settings) -> None:
    initialize_database(settings)
    adapter = FakeAdapter([_bar("000001.SZ", "2024-01-02")])
    adapter.calendar = [{"trade_date": "2024-01-02", "market": "CN", "is_open": 1}]
    pull_daily(["000001.SZ"], "2024-01-02", "2024-01-02", settings=settings, adapter=adapter)


def test_run_sync_job_appends_and_writes_record(tmp_path):
    settings = make_settings(tmp_path)
    _seed_bars(settings)
    adapter = FakeAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    adapter.calendar = [
        {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
        {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
    ]
    row = run_sync_job(settings=settings, adapter=adapter, today="2024-01-03")
    assert row["status"] in {"success", "skipped"}
    assert row["trigger"] == "manual"
    assert row["fail_reason"] in (None, "")
    stored = read_market_daily(symbol="000001.SZ", settings=settings)
    assert {item["trade_date"] for item in stored} == {"2024-01-02", "2024-01-03"}
    listed = list_sync_runs(settings=settings)
    assert listed["total"] == 1
    assert listed["items"][0]["run_id"] == row["run_id"]
    assert listed["items"][0].get("inflight") in (None, 0)
    assert listed["items"][0].get("progress_pct") == 100
    assert query_all("SELECT COUNT(*) AS c FROM data_sync_lock", settings=settings)[0]["c"] == 0


def _occupy_sync(settings: Settings, run_id: str = "run-busy") -> None:
    initialize_database(settings)
    execute(
        """
        INSERT INTO data_sync_run
            (run_id, trigger, status, source, inflight, started_at, created_at)
        VALUES (?, 'manual', 'running', 'baostock', 1, '2099-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00')
        """,
        (run_id,),
        settings=settings,
    )
    execute(
        """
        INSERT INTO data_sync_lock (lock_id, run_id, holder, acquired_at, expires_at)
        VALUES (?, ?, 'manual', '2099-01-01T00:00:00+00:00', '2099-12-31T00:00:00+00:00')
        """,
        (SYNC_LOCK_ID, run_id),
        settings=settings,
    )


def test_sync_rejects_second_running_job(tmp_path):
    settings = make_settings(tmp_path)
    _occupy_sync(settings)
    try:
        start_sync_job(settings=settings, background=False, adapter=FakeAdapter([]), today="2024-01-03")
        raise AssertionError("expected Busy")
    except Busy:
        pass


def test_sync_rejects_reclick_while_running(tmp_path):
    settings = make_settings(tmp_path)
    _seed_bars(settings)
    entered = threading.Event()
    release = threading.Event()

    class HoldAdapter(FakeAdapter):
        def fetch_market_daily(self, symbols, start, end, on_progress=None):
            entered.set()
            assert release.wait(timeout=10)
            return super().fetch_market_daily(symbols, start, end, on_progress=on_progress)

    adapter = HoldAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    adapter.calendar = [
        {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
        {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
    ]
    first_result: dict[str, object] = {}

    def first_job():
        first_result["row"] = start_sync_job(
            settings=settings,
            adapter=adapter,
            today="2024-01-03",
            background=False,
        )

    thread = threading.Thread(target=first_job)
    thread.start()
    assert entered.wait(timeout=10)
    mid = query_all(
        "SELECT * FROM data_sync_run WHERE status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
        settings=settings,
    )[0]
    assert mid["status"] == "running"
    assert int(mid.get("progress_pct") or 0) >= 1
    try:
        start_sync_job(settings=settings, background=False, adapter=FakeAdapter([]), today="2024-01-03")
        raise AssertionError("expected Busy")
    except Busy:
        pass
    release.set()
    thread.join(timeout=15)
    assert first_result["row"]["status"] in {"success", "skipped"}
    assert first_result["row"].get("progress_pct") == 100
    locks = query_all("SELECT COUNT(*) AS c FROM data_sync_lock", settings=settings)[0]["c"]
    inflight = query_all("SELECT COUNT(*) AS c FROM data_sync_run WHERE inflight = 1", settings=settings)[0]["c"]
    assert locks == 0
    assert inflight == 0


def test_sync_api_manual_trigger_and_list(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    _seed_bars(settings)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    adapter = FakeAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    adapter.calendar = [
        {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
        {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
    ]

    def fake_start(**kwargs):
        kwargs["background"] = False
        kwargs["adapter"] = adapter
        kwargs["settings"] = settings
        kwargs["today"] = "2024-01-03"
        return start_sync_job(**kwargs)

    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    monkeypatch.setattr("asqt.api.start_sync_job", fake_start)

    client = TestClient(create_app())
    started = client.post("/api/sync/runs", json={"source": "baostock"})
    assert started.status_code == 200
    body = started.json()
    assert body["status"] in {"success", "skipped", "queued"}
    listed = client.get("/api/sync/runs")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    detail = client.get(f"/api/sync/runs/{body['run_id'] if body.get('run_id') else listed.json()['items'][0]['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] in {"success", "skipped", "quality_failed", "failed"}


def test_sync_api_conflict_when_busy(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    _occupy_sync(settings)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    response = client.post("/api/sync/runs")
    assert response.status_code == 409
    assert query_all("SELECT COUNT(*) AS c FROM data_sync_run", settings=settings)[0]["c"] == 1


def test_recover_orphans_marks_running_failed(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    _occupy_sync(settings)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    count = recover_orphaned_sync_runs(settings)
    assert count == 1
    row = get_sync_run("run-busy", settings=settings)
    assert row["status"] == "failed"
    assert "热加载" in (row.get("fail_reason") or "")
    assert query_all("SELECT COUNT(*) AS c FROM data_sync_lock", settings=settings)[0]["c"] == 0


def test_abort_resets_running_job_without_overwrite(tmp_path):
    settings = make_settings(tmp_path)
    _seed_bars(settings)
    entered = threading.Event()
    release = threading.Event()

    class HoldAdapter(FakeAdapter):
        def fetch_market_daily(self, symbols, start, end, on_progress=None):
            entered.set()
            assert release.wait(timeout=10)
            return super().fetch_market_daily(symbols, start, end, on_progress=on_progress)

    adapter = HoldAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    adapter.calendar = [
        {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
        {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
    ]
    result: dict[str, object] = {}

    def job():
        result["row"] = start_sync_job(
            settings=settings,
            adapter=adapter,
            today="2024-01-03",
            background=False,
        )

    thread = threading.Thread(target=job)
    thread.start()
    assert entered.wait(timeout=10)
    aborted = abort_inflight_sync_runs(settings, reason="人工重置，结束卡住的同步")
    assert len(aborted) == 1
    release.set()
    thread.join(timeout=15)
    row = get_sync_run(aborted[0], settings=settings)
    assert row["status"] == "failed"
    assert "人工重置" in (row.get("fail_reason") or "")
    assert result["row"]["status"] == "failed"
    assert query_all("SELECT COUNT(*) AS c FROM data_sync_lock", settings=settings)[0]["c"] == 0


def test_vendor_asof_ready_requires_every_symbol_on_asof():
    adapter = FakeAdapter([_bar("000001.SZ", "2026-09-08"), _bar("510300.SH", "2026-09-07")])
    covered = vendor_asof_ready(adapter, ["000001.SZ", "510300.SH"], "2026-09-08")
    assert covered["ready"] is False
    assert covered["have"] == 1
    adapter.rows.append(_bar("510300.SH", "2026-09-08"))
    assert vendor_asof_ready(adapter, ["000001.SZ", "510300.SH"], "2026-09-08")["ready"] is True


def test_auto_waits_for_vendor_bars_before_deadline(tmp_path):
    from datetime import datetime

    from asqt.session import SHANGHAI

    settings = make_settings(tmp_path)
    initialize_database(settings)
    now = datetime(2026, 9, 8, 16, 45, tzinfo=SHANGHAI)
    kwargs = {
        "settings": settings,
        "now": now,
        "symbols": ["000001.SZ"],
        "asof": "2026-09-08",
        "enabled": True,
    }
    waiting = FakeAdapter([_bar("000001.SZ", "2026-09-07")])
    assert should_auto_run(adapter=waiting, **kwargs) is False
    ready = FakeAdapter([_bar("000001.SZ", "2026-09-08")])
    assert should_auto_run(adapter=ready, **kwargs) is True


def test_auto_after_deadline_matches_legacy_retry(tmp_path):
    from datetime import datetime

    from asqt.session import SHANGHAI

    settings = make_settings(tmp_path)
    initialize_database(settings)
    deadline = datetime(2026, 9, 8, 17, 30, tzinfo=SHANGHAI)
    empty = FakeAdapter([])
    assert should_auto_run(
        settings=settings,
        now=deadline,
        adapter=empty,
        symbols=["000001.SZ"],
        asof="2026-09-08",
        enabled=True,
    )
    execute(
        """
        INSERT INTO data_sync_run
            (run_id, trigger, status, source, finished_at, created_at)
        VALUES ('auto-qc-1', 'auto', 'quality_failed', 'baostock',
                '2026-09-08T09:31:00+00:00', '2026-09-08T09:31:00+00:00')
        """,
        settings=settings,
    )
    later = datetime(2026, 9, 8, 17, 35, tzinfo=SHANGHAI)
    assert should_auto_run(
        settings=settings,
        now=later,
        adapter=empty,
        symbols=["000001.SZ"],
        asof="2026-09-08",
        enabled=True,
    )
    execute(
        """
        INSERT INTO data_sync_run
            (run_id, trigger, status, source, finished_at, created_at)
        VALUES ('auto-ok-1', 'auto', 'success', 'baostock',
                '2026-09-08T09:40:00+00:00', '2026-09-08T09:40:00+00:00')
        """,
        settings=settings,
    )
    assert should_auto_run(
        settings=settings,
        now=later,
        adapter=empty,
        symbols=["000001.SZ"],
        asof="2026-09-08",
        enabled=True,
    ) is False
