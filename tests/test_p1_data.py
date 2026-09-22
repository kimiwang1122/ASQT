from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.config import Settings
from asqt.normalize import StandardNormalizer, repair_placeholder_adj_factors
from asqt.db import initialize_database
from asqt.pipeline import pull_daily, pull_daily_append, resolve_append_window
from asqt.quality import ContractQualityChecker
from asqt.storage import read_market_daily


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
        total = len(symbols)
        if on_progress:
            on_progress(0, total, None)
        rows = [row for row in self.rows if row["symbol"] in wanted]
        if on_progress:
            on_progress(total, total, symbols[-1] if symbols else None)
        return rows

    def fetch_trade_calendar(self, start: str, end: str) -> list[dict]:
        return list(self.calendar)


def test_normalizer_maps_vendor_row_to_contract():
    rows = StandardNormalizer().normalize_market_daily([_bar("000001.SZ", "2024-01-02")], "baostock")
    assert rows[0]["symbol"] == "000001.SZ"
    assert rows[0]["trade_date"] == "2024-01-02"
    assert rows[0]["source"] == "baostock"
    assert rows[0]["adj_factor"] == 1.0


def test_quality_blocks_null_fields_and_bad_ohlc():
    checker = ContractQualityChecker()
    missing = checker.check(
        "market_daily",
        records=[{"symbol": "000001.SZ", "trade_date": "2024-01-02", "open": None, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 1, "adj_factor": 1, "source": "x", "version": "x"}],
    )
    assert missing["trade_allowed"] is False
    assert any(item["check_type"] == "missing" for item in missing["issues"])

    ohlc = checker.check(
        "market_daily",
        records=[{"symbol": "000001.SZ", "trade_date": "2024-01-02", "open": 10, "high": 9, "low": 9.5, "close": 10, "volume": 1, "amount": 1, "adj_factor": 1, "source": "x", "version": "x"}],
    )
    assert any(item["check_type"] == "range" and item["severity"] == "block" for item in ohlc["issues"])


def test_quality_adj_jump_and_point_in_time():
    checker = ContractQualityChecker()
    jump = checker.check(
        "market_daily",
        records=[
            {"symbol": "000001.SZ", "trade_date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 1, "adj_factor": 1.0, "source": "x", "version": "x"},
            {"symbol": "000001.SZ", "trade_date": "2024-01-03", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 1, "adj_factor": 3.0, "source": "x", "version": "x"},
        ],
        corporate_actions=[],
    )
    assert any(item["check_type"] == "adj_conflict" and item["severity"] == "block" for item in jump["issues"])

    pit = checker.check(
        "market_daily",
        records=[{"symbol": "000001.SZ", "trade_date": "2024-01-10", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 1, "adj_factor": 1.0, "source": "x", "version": "x"}],
        instruments=[{"symbol": "000001.SZ", "list_date": "2020-01-01", "delist_date": "2024-01-05"}],
    )
    assert any(item["check_type"] == "point_in_time" for item in pit["issues"])


def test_pipeline_writes_raw_parquet_and_passes_quality(tmp_path):
    settings = make_settings(tmp_path)
    adapter = FakeAdapter(
        [
            _bar("000001.SZ", "2024-01-02"),
            _bar("000001.SZ", "2024-01-03"),
        ]
    )
    result = pull_daily(["000001.SZ"], "2024-01-02", "2024-01-03", settings=settings, adapter=adapter)
    assert Path(result["raw_path"]).exists()
    assert result["quality"]["trade_allowed"] is True
    stored = read_market_daily(symbol="000001.SZ", settings=settings)
    assert len(stored) == 2
    assert stored[0]["source"] == "baostock"


def test_upsert_keeps_other_dates_for_same_symbol(tmp_path):
    settings = make_settings(tmp_path)
    first = FakeAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    pull_daily(["000001.SZ"], "2024-01-02", "2024-01-03", settings=settings, adapter=first)
    second = FakeAdapter([_bar("000001.SZ", "2024-01-02", close=12)])
    second.source_id = "akshare"
    pull_daily(["000001.SZ"], "2024-01-02", "2024-01-02", settings=settings, adapter=second, run_check=False)
    stored = read_market_daily(symbol="000001.SZ", settings=settings)
    by_date = {row["trade_date"]: row for row in stored}
    assert set(by_date) == {"2024-01-02", "2024-01-03"}
    assert by_date["2024-01-02"]["source"] == "akshare"
    assert by_date["2024-01-03"]["source"] == "baostock"
    assert by_date["2024-01-02"]["close"] == 12


def test_repair_placeholder_adj_carries_previous_factor():
    rows = [
        {"symbol": "510500.SH", "trade_date": "2026-09-04", "close": 7.673, "adj_factor": 0.337},
        {"symbol": "510500.SH", "trade_date": "2026-09-07", "close": 7.771, "adj_factor": 1.0},
        {"symbol": "159915.SZ", "trade_date": "2026-09-04", "close": 3.305, "adj_factor": 1.0},
        {"symbol": "159915.SZ", "trade_date": "2026-09-07", "close": 3.414, "adj_factor": 1.0},
    ]
    assert repair_placeholder_adj_factors(rows) == 1
    by = {(row["symbol"], row["trade_date"]): row["adj_factor"] for row in rows}
    assert by[("510500.SH", "2026-09-07")] == 0.337
    assert by[("159915.SZ", "2026-09-07")] == 1.0


def test_append_placeholder_etf_adj_does_not_block_quality(tmp_path):
    settings = make_settings(tmp_path)
    first = FakeAdapter(
        [
            _bar("510500.SH", "2026-09-03", open=7.7, close=7.781, high=7.9, low=7.6, adj_factor=0.337),
            _bar("510500.SH", "2026-09-04", open=7.7, close=7.673, high=7.8, low=7.5, adj_factor=0.337),
        ],
        calendar=[
            {"trade_date": "2026-09-03", "market": "CN", "is_open": 1},
            {"trade_date": "2026-09-04", "market": "CN", "is_open": 1},
        ],
    )
    pull_daily(["510500.SH"], "2026-09-03", "2026-09-04", settings=settings, adapter=first)
    second = FakeAdapter(
        [_bar("510500.SH", "2026-09-07", open=7.7, close=7.771, high=7.9, low=7.6, adj_factor=1.0)],
        calendar=[{"trade_date": "2026-09-07", "market": "CN", "is_open": 1}],
    )
    pull_daily(["510500.SH"], "2026-09-07", "2026-09-07", settings=settings, adapter=second)
    stored = {row["trade_date"]: row for row in read_market_daily(symbol="510500.SH", settings=settings)}
    assert stored["2026-09-07"]["adj_factor"] == 0.337
    from asqt.quality import ContractQualityChecker

    full = ContractQualityChecker().check("market_daily", records=list(stored.values()))
    assert full["trade_allowed"] is True


def test_pipeline_warns_when_calendar_day_missing(tmp_path):
    settings = make_settings(tmp_path)
    adapter = FakeAdapter(
        [_bar("000001.SZ", "2024-01-02")],
        calendar=[
            {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
            {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
        ],
    )
    result = pull_daily(["000001.SZ"], "2024-01-02", "2024-01-03", settings=settings, adapter=adapter)
    # Isolated calendar holes (halts / source gaps) stay visible as warn, not hard blocks.
    assert result["quality"]["trade_allowed"] is True
    assert any(
        item["check_type"] == "missing" and item["severity"] == "warn"
        for item in result["quality"]["issues"]
    )


def test_api_does_not_import_baostock_and_marks_p1_ports_wired(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    import sys

    sys.modules.pop("baostock", None)
    sys.modules.pop("akshare", None)
    client = TestClient(create_app())
    ports = client.get("/api/ports").json()
    by_name = {item["name"]: item for item in ports}
    assert by_name["QualityChecker"]["status"] == "wired"
    assert by_name["DataSourceAdapter"]["status"] == "wired"
    assert by_name["ExecutionAdapter"]["status"] == "wired"
    assert by_name["AlertService"]["status"] == "wired"
    assert "baostock" not in sys.modules
    assert "akshare" not in sys.modules


def test_session_asof_before_and_after_close():
    from datetime import datetime

    from asqt.session import SHANGHAI, session_asof_date

    morning = datetime(2026, 9, 8, 2, 52, tzinfo=SHANGHAI)
    close = datetime(2026, 9, 8, 16, 30, tzinfo=SHANGHAI)
    assert session_asof_date(morning) == "2026-09-07"
    assert session_asof_date(close) == "2026-09-08"


def test_check_market_daily_ignores_unclosed_session(tmp_path, monkeypatch):
    from asqt.db import execute
    from asqt.pipeline import check_market_daily

    settings = make_settings(tmp_path)
    initialize_database(settings)
    monkeypatch.setattr("asqt.pipeline.session_asof_date", lambda now=None: "2026-09-07")
    first = FakeAdapter(
        [_bar("000001.SZ", "2026-09-07")],
        calendar=[
            {"trade_date": "2026-09-07", "market": "CN", "is_open": 1},
            {"trade_date": "2026-09-08", "market": "CN", "is_open": 1},
        ],
    )
    pull_daily(["000001.SZ"], "2026-09-07", "2026-09-08", settings=settings, adapter=first, run_check=False)
    execute(
        """
        INSERT OR REPLACE INTO trade_calendar
            (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
        VALUES ('2026-09-08', 'CN', 1, '09:30', '15:00', '2026-09-07', NULL)
        """,
        settings=settings,
    )
    result = check_market_daily(settings=settings, expected_symbols=["000001.SZ"])
    assert result["trade_allowed"] is True
    assert not any(item.get("trade_date") == "2026-09-08" for item in result["issues"])
    windowed = check_market_daily(
        settings=settings,
        expected_symbols=["000001.SZ"],
        start="2026-09-07",
    )
    assert windowed["trade_allowed"] is True


def test_resolve_append_window_from_latest_and_empty():
    window = resolve_append_window(max_trade_date="2026-09-03", today="2026-09-07", overlap_days=1)
    assert window["ok"] is True
    assert window["start"] == "2026-09-03"
    assert window["end"] == "2026-09-07"
    empty = resolve_append_window(max_trade_date=None, today="2026-09-07")
    assert empty["ok"] is False
    assert empty["reason"] == "no_stored_bars"


def test_pull_daily_append_skips_without_store_and_merges_new_dates(tmp_path):
    settings = make_settings(tmp_path)
    skipped = pull_daily_append(["000001.SZ"], settings=settings, adapter=FakeAdapter([]), today="2024-01-03")
    assert skipped["skipped"] is True
    assert skipped["reason"] == "no_stored_bars"

    first = FakeAdapter([_bar("000001.SZ", "2024-01-02")])
    first.calendar = [{"trade_date": "2024-01-02", "market": "CN", "is_open": 1}]
    pull_daily(["000001.SZ"], "2024-01-02", "2024-01-02", settings=settings, adapter=first)
    second = FakeAdapter([_bar("000001.SZ", "2024-01-02"), _bar("000001.SZ", "2024-01-03")])
    second.calendar = [
        {"trade_date": "2024-01-02", "market": "CN", "is_open": 1},
        {"trade_date": "2024-01-03", "market": "CN", "is_open": 1},
    ]
    result = pull_daily_append(["000001.SZ"], settings=settings, adapter=second, today="2024-01-03")
    assert result["skipped"] is False
    stored = read_market_daily(symbol="000001.SZ", settings=settings)
    assert {row["trade_date"] for row in stored} == {"2024-01-02", "2024-01-03"}
    from asqt.storage import market_daily_row_count

    assert market_daily_row_count(settings) == 2


def test_upsert_empty_records_does_not_wipe_parquet(tmp_path):
    from asqt.storage import upsert_market_daily

    settings = make_settings(tmp_path)
    upsert_market_daily(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-02",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 1,
                "amount": 1,
                "adj_factor": 1,
                "source": "x",
                "version": "x",
            }
        ],
        settings=settings,
    )
    upsert_market_daily([], settings=settings)
    stored = read_market_daily(settings=settings)
    assert len(stored) == 1
    assert stored[0]["symbol"] == "000001.SZ"


def test_format_issue_diff_adj_scale_and_silent():
    from asqt.quality import format_issue_diff

    scale = format_issue_diff(
        "adj_factor_scale n=500 adj_factor stored=102.382 peer=113.936 rel=0.1014"
    )
    assert "500 个交易日" in scale
    assert "不阻断交易" in scale
    silent = format_issue_diff(
        "silent_jump_inconsistent factor_ratio=1.033382 price_ratio=0.998103"
    )
    assert "复权因子变动" in silent
    assert "对照公告" in silent
