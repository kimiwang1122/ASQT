from __future__ import annotations

from asqt.db import execute, initialize_database
from asqt.instrument_lookup import instrument_profile, search_instruments
from asqt.storage import write_market_daily
from tests.test_p1_data import make_settings


def _seed(settings, *, name: str = "平安银行") -> None:
    initialize_database(settings)
    execute(
        """
        INSERT INTO instrument_master
            (symbol, name, instrument_type, exchange, board, list_date, status, is_st)
        VALUES ('000001.SZ', ?, 'stock', 'SZ', 'main', '1991-04-03', 'listed', 0)
        """,
        (name,),
        settings=settings,
    )
    execute(
        """
        INSERT INTO instrument_master
            (symbol, name, instrument_type, exchange, board, list_date, status, is_st)
        VALUES ('510300.SH', '沪深300ETF', 'etf', 'SH', 'broad_index', '2012-05-28', 'listed', 0)
        """,
        settings=settings,
    )
    execute(
        "INSERT INTO symbol_tag (tag, symbol, source, note) VALUES ('hs300', '000001.SZ', 'universe', '')",
        settings=settings,
    )
    write_market_daily(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": "2026-09-18",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.0,
                "volume": 1000,
                "amount": 10000,
                "adj_factor": 1.0,
                "source": "test",
                "version": "lookup",
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2026-09-19",
                "open": 10.1,
                "high": 10.5,
                "low": 10.0,
                "close": 10.4,
                "volume": 1200,
                "amount": 12480,
                "adj_factor": 1.0,
                "source": "test",
                "version": "lookup",
            },
        ],
        settings=settings,
    )


def test_search_instruments_fuzzy_code_and_name(tmp_path):
    settings = make_settings(tmp_path)
    _seed(settings)
    by_code = search_instruments("000001", settings=settings)
    assert by_code and by_code[0]["symbol"] == "000001.SZ"
    by_name = search_instruments("平安", settings=settings)
    assert any(row["symbol"] == "000001.SZ" for row in by_name)
    assert search_instruments("", settings=settings) == []


def test_lookup_api_search_and_profile(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from asqt.api import create_app
    from asqt import config as config_module

    settings = make_settings(tmp_path)
    _seed(settings)
    monkeypatch.setattr("asqt.instrument_lookup._tushare_f10", lambda *a, **k: None)
    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    hits = client.get("/api/lookup/search", params={"q": "平安"}).json()
    assert hits["total"] >= 1
    assert hits["items"][0]["symbol"] == "000001.SZ"
    profile = client.get("/api/lookup/profile", params={"symbol": "000001"}).json()
    assert profile["instrument"]["symbol"] == "000001.SZ"
    assert profile["quote"]["close"] == 10.4
    missing = client.get("/api/lookup/profile", params={"symbol": "ZZZZ.XX"})
    assert missing.status_code == 404


def test_instrument_profile_local_quote_without_tushare(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    _seed(settings)
    monkeypatch.setattr("asqt.instrument_lookup._tushare_f10", lambda *a, **k: None)
    profile = instrument_profile("000001.SZ", settings=settings, live=True)
    assert profile is not None
    assert profile["instrument"]["name"] == "平安银行"
    assert "hs300" in profile["tags"]
    assert profile["quote"]["close"] == 10.4
    assert abs(profile["quote"]["change_pct"] - 0.04) < 1e-9
    assert profile["sources"]["local"] is True
    assert profile["sources"]["tushare"] is False
    assert instrument_profile("not-a-stock", settings=settings) is None


def test_latest_daily_basic_retries_older_session(monkeypatch):
    from asqt.instrument_lookup import _latest_daily_basic

    def fake_query(_adapter, api, params, _fields):
        assert api == "daily_basic"
        if params["trade_date"] == "20260921":
            return []
        return [{"pe": 5.2, "pb": 0.9, "trade_date": params["trade_date"]}]

    monkeypatch.setattr("asqt.instrument_lookup._safe_query", fake_query)
    row = _latest_daily_basic(object(), "000001.SZ", ["2026-09-21", "2026-09-19"])
    assert row["pe"] == 5.2
    assert row["trade_date"] == "20260919"
