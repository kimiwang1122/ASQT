from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.bootstrap import seed_demo
from asqt.config import Settings, ensure_runtime_dirs
from asqt.contracts import MARKET_DAILY_COLUMNS, REQUIRED_TABLES, TABLE_COLUMNS
from asqt.db import assert_contract_schema, executemany, initialize_database, query_all, table_columns
from asqt.ports import PORT_NAMES, DataSourceAdapter, QualityChecker
from asqt.storage import market_daily_path, read_market_daily, write_market_daily


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


def test_initialize_database_creates_contract_tables(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    tables = query_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        settings=settings,
    )
    names = {row["name"] for row in tables}
    for table in REQUIRED_TABLES:
        assert table in names


def test_contract_columns_match_dictionary(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    assert_contract_schema(settings)
    for table, expected in TABLE_COLUMNS.items():
        actual = table_columns(table, settings=settings)
        for column in expected:
            assert column in actual


def test_runtime_layout_directories_are_created(tmp_path):
    settings = make_settings(tmp_path)
    ensure_runtime_dirs(settings)
    for path in (
        settings.raw_dir,
        settings.standard_dir,
        settings.qlib_dir,
        settings.experiment_dir,
        settings.logs_dir,
        settings.parquet_dir,
    ):
        assert path.exists() and path.is_dir()


def test_seed_demo_writes_sqlite_metadata_and_parquet_market_data(tmp_path):
    settings = make_settings(tmp_path)
    result = seed_demo(settings)
    instruments = query_all(
        "SELECT symbol, instrument_type FROM instrument_master ORDER BY symbol",
        settings=settings,
    )
    records = read_market_daily(symbol="510300.SH", settings=settings)
    sources = query_all("SELECT source_id, quota, cost, owner FROM data_source", settings=settings)
    calendar = query_all("SELECT trade_date FROM trade_calendar ORDER BY trade_date", settings=settings)
    limits = query_all("SELECT symbol FROM limit_suspension", settings=settings)
    factors = query_all("SELECT factor_name FROM factor_signal", settings=settings)

    assert result["market_daily_rows"] == 4
    assert {row["symbol"] for row in instruments} == {"000001.SZ", "510300.SH"}
    assert instruments[0]["instrument_type"] == "stock"
    assert len(records) == 2
    assert records[0]["source"] == "demo"
    assert set(records[0]) >= set(MARKET_DAILY_COLUMNS)
    assert sources[0]["owner"] == "asqt-maintainer"
    assert sources[0]["quota"] == "unlimited-local"
    assert len(calendar) == 3
    assert len(limits) == 4
    assert factors[0]["factor_name"] == "momentum_20d"
    assert market_daily_path(settings).exists()
    assert str(settings.standard_dir) in result["parquet"]


def test_seed_demo_does_not_overwrite_larger_market_daily(tmp_path):
    settings = make_settings(tmp_path)
    seed_demo(settings)
    rows = read_market_daily(settings=settings)
    extra = dict(rows[0])
    extra["trade_date"] = "2026-08-19"
    extra["symbol"] = "000002.SZ"
    write_market_daily(rows + [extra], settings=settings)
    result = seed_demo(settings)
    kept = read_market_daily(settings=settings)
    assert result["skipped_market_daily"] is True
    assert len(kept) == 5
    assert any(row["symbol"] == "000002.SZ" for row in kept)


def test_data_source_migration_adds_missing_columns(tmp_path):
    settings = make_settings(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    import sqlite3

    with sqlite3.connect(settings.database_path) as conn:
        conn.execute(
            """
            CREATE TABLE data_source (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                purpose TEXT NOT NULL,
                auth_status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                health_status TEXT NOT NULL DEFAULT 'unknown',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

    initialize_database(settings)
    columns = set(table_columns("data_source", settings=settings))
    assert {"quota", "cost", "owner"} <= columns


def test_ports_are_importable_protocols():
    assert len(PORT_NAMES) >= 9
    assert issubclass(type(DataSourceAdapter), type)
    assert issubclass(type(QualityChecker), type)


def test_api_smoke_health_status_and_market(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html><body>ASQT</body></html>", encoding="utf-8")
    seed_demo(settings)

    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)

    client = TestClient(create_app())
    health = client.get("/api/health")
    status = client.get("/api/status")
    market = client.get("/api/market/daily", params={"symbol": "510300.SH"})
    sources = client.get("/api/data-sources")
    ports = client.get("/api/ports")
    layout = client.get("/api/layout")
    calendar = client.get("/api/calendar")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert status.status_code == 200
    body = status.json()
    assert body["instruments"] == 2
    assert body["trade_calendar_rows"] == 3
    assert body["factor_signal_rows"] == 1
    assert market.status_code == 200
    assert len(market.json()) == 2
    unfiltered = client.get("/api/market/daily")
    assert unfiltered.status_code == 200
    assert 1 <= len(unfiltered.json()) <= 100
    assert sources.json()[0]["owner"] == "asqt-maintainer"
    assert {item["name"] for item in ports.json()} >= set(PORT_NAMES)
    assert "raw_data" in layout.json()
    assert len(calendar.json()) == 3


def test_quality_issues_api_paginates_and_does_not_return_full_list(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    initialize_database(settings)
    rows = [
        (
            f"iss-{i:03d}",
            "market_daily",
            "000001.SZ",
            "2026-01-01",
            "reconcile",
            "warn",
            "closed" if i < 5 else "open",
            "baostock",
            "akshare",
            f"diff-{i}",
        )
        for i in range(25)
    ]
    executemany(
        """
        INSERT INTO quality_issue
            (issue_id, dataset, symbol, trade_date, check_type, severity, status, source_a, source_b, diff)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
        settings=settings,
    )

    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)

    client = TestClient(create_app())
    first = client.get("/api/quality/issues", params={"page": 1, "page_size": 10})
    assert first.status_code == 200
    body = first.json()
    assert set(body) >= {"items", "total", "page", "page_size", "pages", "status"}
    assert body["total"] == 20
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["pages"] == 2
    assert len(body["items"]) == 10
    assert all(item["status"] != "closed" for item in body["items"])

    second = client.get("/api/quality/issues", params={"page": 2, "page_size": 10, "status": "open"})
    assert len(second.json()["items"]) == 10
    assert {row["issue_id"] for row in first.json()["items"]}.isdisjoint(
        {row["issue_id"] for row in second.json()["items"]}
    )

    closed = client.get("/api/quality/issues", params={"status": "closed", "page_size": 100})
    assert closed.json()["total"] == 5
    assert len(closed.json()["items"]) == 5

    all_rows = client.get("/api/quality/issues", params={"status": "all", "page_size": 100})
    assert all_rows.json()["total"] == 25
    assert len(all_rows.json()["items"]) == 25

    default = client.get("/api/quality/issues")
    assert default.json()["page_size"] == 20
    assert len(default.json()["items"]) <= 20

    filtered = client.get(
        "/api/quality/issues",
        params={
            "status": "all",
            "trade_date": "2026-01-01",
            "severity": "warn",
            "code": "000001",
            "sort": "issue_id",
            "order": "asc",
            "page_size": 100,
        },
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 25
    assert filtered_body["sort"] == "created_at"
    assert filtered_body["order"] == "asc"
    assert all(item["severity"] == "warn" for item in filtered_body["items"])
    assert all("000001" in (item["symbol"] or "") for item in filtered_body["items"])
    assert all(item["code"] == "000001" for item in filtered_body["items"])
    assert all(item["exchange"] == "SZ" for item in filtered_body["items"])

    by_status = client.get(
        "/api/quality/issues",
        params={"status": "all", "sort": "status", "order": "asc", "page_size": 100},
    )
    statuses = [item["status"] for item in by_status.json()["items"]]
    assert statuses == sorted(statuses)

    sample = client.get("/api/quality/issues", params={"status": "open", "page_size": 1}).json()["items"][0]
    assert sample.get("diff_label")
    closed_one = client.post(f"/api/quality/issues/{sample['issue_id']}/close")
    assert closed_one.status_code == 200
    assert closed_one.json()["issue"]["status"] == "closed"
    missing = client.post("/api/quality/issues/missing-id/close")
    assert missing.status_code == 404
