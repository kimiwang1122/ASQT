"""Focused tests for Record schema upsert / query / pull API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.config import Settings
from asqt.pipeline import pull_daily
from asqt.provider_registry import PROVIDER_REGISTRY, provider_provides, providers_for
from asqt.records import RECORD_SCHEMAS, query_records, record_parquet_path, upsert_records
from asqt.storage import read_market_daily, upsert_market_daily


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


def _row(symbol: str, trade_date: str, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 1000,
        "amount": 10500.0,
        "adj_factor": 1.0,
        "source": "baostock",
        "version": "test",
    }
    row.update(overrides)
    return row


def _bar(symbol: str, trade_date: str, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "date": trade_date,
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10.5,
        "volume": 1000,
        "amount": 10500,
        "adj_factor": 1.0,
        "preclose": 10,
        "tradestatus": "1",
        "isST": "0",
        "name": "Demo",
        "ipoDate": "2020-01-01",
        "outDate": "",
        "status": "1",
    }
    row.update(overrides)
    return row


class FakeAdapter:
    source_id = "baostock"

    def __init__(self, rows: list[dict], calendar: list[dict] | None = None) -> None:
        self.rows = rows
        self.calendar = calendar or [
            {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
            {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
        ]

    def health(self) -> dict:
        return {"ok": True, "source_id": self.source_id}

    def fetch_market_daily(self, symbols: list[str], start: str, end: str, on_progress=None) -> list[dict]:
        wanted = set(symbols)
        return [row for row in self.rows if row["symbol"] in wanted]

    def fetch_trade_calendar(self, start: str, end: str) -> list[dict]:
        return list(self.calendar)


def test_record_schemas_register_market_daily():
    assert "market_daily" in RECORD_SCHEMAS
    assert RECORD_SCHEMAS["market_daily"]["pk"] == ("symbol", "trade_date")
    assert providers_for("market_daily") == ["baostock", "tushare", "akshare"]
    assert providers_for("market_daily", include_optional=False) == ["baostock"]
    assert provider_provides("baostock", "market_daily") is True
    assert provider_provides("baostock", "market_event") is False
    assert set(PROVIDER_REGISTRY) == {"baostock", "akshare", "tushare"}


def test_upsert_records_idempotent_and_preserves_other_keys(tmp_path):
    settings = make_settings(tmp_path)
    path = upsert_records(
        "market_daily",
        [_row("000001.SZ", "2024-01-02"), _row("000001.SZ", "2024-01-03")],
        settings=settings,
    )
    assert path == settings.standard_dir / "market_daily.parquet"
    assert path.exists()

    upsert_records(
        "market_daily",
        [_row("000001.SZ", "2024-01-02", close=12.0, source="akshare")],
        settings=settings,
    )
    rows = query_records("market_daily", settings=settings)
    by_date = {row["trade_date"]: row for row in rows}
    assert set(by_date) == {"2024-01-02", "2024-01-03"}
    assert by_date["2024-01-02"]["close"] == 12.0
    assert by_date["2024-01-02"]["source"] == "akshare"
    assert by_date["2024-01-03"]["source"] == "baostock"

    upsert_records("market_daily", [], settings=settings)
    assert len(query_records("market_daily", settings=settings)) == 2


def test_upsert_market_daily_reuses_records_merge(tmp_path):
    settings = make_settings(tmp_path)
    upsert_market_daily([_row("510300.SH", "2024-01-02")], settings=settings)
    upsert_records(
        "market_daily",
        [_row("510300.SH", "2024-01-02", close=4.2), _row("510300.SH", "2024-01-03")],
        settings=settings,
    )
    via_storage = read_market_daily(symbol="510300.SH", settings=settings)
    via_records = query_records("market_daily", symbol="510300.SH", settings=settings)
    assert via_storage == via_records
    assert {row["trade_date"] for row in via_storage} == {"2024-01-02", "2024-01-03"}
    assert via_storage[0]["close"] == 4.2 or via_storage[1]["close"] == 4.2
    by_date = {row["trade_date"]: row for row in via_storage}
    assert by_date["2024-01-02"]["close"] == 4.2


def test_query_records_filters_and_path(tmp_path):
    settings = make_settings(tmp_path)
    upsert_records(
        "market_daily",
        [
            _row("000001.SZ", "2024-01-02"),
            _row("000001.SZ", "2024-01-03"),
            _row("510300.SH", "2024-01-02"),
        ],
        settings=settings,
    )
    assert record_parquet_path("market_daily", settings).name == "market_daily.parquet"
    filtered = query_records(
        "market_daily",
        symbol="000001.SZ",
        start="2024-01-03",
        settings=settings,
    )
    assert len(filtered) == 1
    assert filtered[0]["trade_date"] == "2024-01-03"
    newest = query_records("market_daily", symbol="000001.SZ", limit=1, newest_first=True, settings=settings)
    assert newest[0]["trade_date"] == "2024-01-03"


def test_pipeline_pull_writes_same_parquet_as_records(tmp_path):
    settings = make_settings(tmp_path)
    adapter = FakeAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    result = pull_daily(["000001.SZ"], "2024-01-02", "2024-01-03", settings=settings, adapter=adapter)
    assert Path(result["parquet"]).exists()
    stored = query_records("market_daily", symbol="000001.SZ", settings=settings)
    assert len(stored) == 2


def test_api_records_query_upsert_and_pull(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)

    adapter = FakeAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    monkeypatch.setattr("asqt.pipeline.build_adapter", lambda source: adapter)

    client = TestClient(create_app())
    missing = client.get("/api/records/no_such_schema")
    assert missing.status_code == 404

    upsert = client.post(
        "/api/records/market_daily/upsert",
        json={"rows": [_row("000001.SZ", "2024-01-02")]},
    )
    assert upsert.status_code == 200
    assert upsert.json()["upserted"] == 1

    listed = client.get("/api/records/market_daily", params={"symbol": "000001.SZ"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    pulled = client.post(
        "/api/records/market_daily/pull",
        json={
            "source": "baostock",
            "symbols": ["000001.SZ"],
            "start": "2024-01-02",
            "end": "2024-01-03",
            "run_check": False,
        },
    )
    assert pulled.status_code == 200
    body = pulled.json()
    assert body["schema"] == "market_daily"
    assert body["normalized_rows"] == 2
    assert len(query_records("market_daily", symbol="000001.SZ", settings=settings)) == 2

    append = client.post(
        "/api/records/market_daily/pull",
        json={
            "source": "baostock",
            "symbols": ["000001.SZ"],
            "today": "2024-01-03",
            "overlap_days": 1,
            "run_check": False,
        },
    )
    assert append.status_code == 200
    assert append.json().get("skipped") is False or append.json().get("normalized_rows") is not None

    bad_source = client.post(
        "/api/records/market_daily/pull",
        json={"source": "unknown_vendor", "symbols": ["000001.SZ"]},
    )
    assert bad_source.status_code == 400
