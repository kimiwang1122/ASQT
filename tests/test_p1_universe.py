from __future__ import annotations

from pathlib import Path

from asqt.db import initialize_database, query_all
from asqt.pipeline import pull_daily
from asqt.universe import UniverseError, apply_universe, load_poc_universe, validate_universe
from tests.test_p1_data import FakeAdapter, _bar, make_settings


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(row[key] for key in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stock(**overrides) -> dict[str, str]:
    row = {
        "symbol": "000001.SZ",
        "name": "平安银行",
        "instrument_type": "stock",
        "exchange": "SZ",
        "board": "main",
        "pool": "hs300",
        "index_name": "沪深300",
        "reason": "test",
        "asof_date": "2026-09-03",
    }
    row.update(overrides)
    return row


def _etf(**overrides) -> dict[str, str]:
    row = {
        "symbol": "510300.SH",
        "name": "沪深300ETF",
        "instrument_type": "etf",
        "exchange": "SH",
        "board": "broad_index",
        "pool": "etf_broad",
        "index_name": "沪深300",
        "reason": "test",
        "asof_date": "2026-09-03",
    }
    row.update(overrides)
    return row


def test_repo_poc_universe_meets_policy():
    payload = load_poc_universe()
    assert len(payload["stocks"]) >= 50
    assert 5 <= len(payload["etfs"]) <= 50
    assert all(row["exchange"] in {"SH", "SZ"} for row in payload["stocks"])
    indexes = {row["index_name"] for row in payload["etfs"]}
    assert len(indexes) == len(payload["etfs"])
    assert {
        "沪深300",
        "中证500",
        "中证1000",
        "创业板指",
        "科创50",
        "上证50",
    } <= indexes
    assert any(row["board"] == "sector" for row in payload["etfs"])
    assert any(row["pool"] == "etf_sector_fallback" for row in payload["etfs"])


def test_universe_rejects_bse_and_duplicate_etf_index():
    stocks = [_stock(), _stock(symbol="920000.BJ", exchange="BJ", board="bse", name="北交所")]
    etfs = [_etf(), _etf(symbol="159919.SZ", exchange="SZ", name="嘉实沪深300ETF")]
    try:
        validate_universe(stocks, etfs, min_stock=1, min_etf=1)
        raise AssertionError("expected UniverseError")
    except UniverseError as exc:
        text = str(exc)
        assert "BSE" in text or "920000.BJ" in text
        assert "duplicate etf index" in text


def test_apply_universe_writes_instrument_master(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    stocks = [_stock(symbol=f"{i:03d}001.SZ", name=f"S{i}") for i in range(50)]
    # 000001, 001001, ... infer 000/001 as main. 049001 still main.
    etfs = [
        _etf(),
        _etf(symbol="510500.SH", name="中证500ETF", index_name="中证500"),
        _etf(symbol="512100.SH", name="中证1000ETF", index_name="中证1000"),
        _etf(symbol="159915.SZ", name="创业板ETF", exchange="SZ", index_name="创业板指"),
        _etf(symbol="588000.SH", name="科创50ETF", index_name="科创50"),
    ]
    _write_csv(tmp_path / "docs" / "p0" / "universe_stock.csv", stocks)
    _write_csv(tmp_path / "docs" / "p0" / "universe_etf.csv", etfs)
    result = apply_universe(settings)
    assert result["stocks"] == 50
    assert result["etfs"] == 5
    rows = query_all("SELECT symbol, instrument_type FROM instrument_master ORDER BY symbol", settings=settings)
    assert len(rows) == 55
    assert any(item["instrument_type"] == "etf" for item in rows)


def test_pull_daily_akshare_source_id_with_fake_adapter(tmp_path):
    settings = make_settings(tmp_path)
    adapter = FakeAdapter(
        [
            _bar("000001.SZ", "2024-01-02"),
            _bar("000001.SZ", "2024-01-03"),
        ]
    )
    adapter.source_id = "akshare"
    result = pull_daily(
        ["000001.SZ"],
        "2024-01-02",
        "2024-01-03",
        settings=settings,
        adapter=adapter,
        source="akshare",
    )
    assert result["source_id"] == "akshare"
    sources = query_all("SELECT source_id, priority FROM data_source", settings=settings)
    assert sources[0]["source_id"] == "akshare"
    assert sources[0]["priority"] == 20
