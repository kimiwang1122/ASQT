"""Focused tests for market_event asof / fixture import / mocked Tushare pull / pilot strategy."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.config import Settings
from asqt.contracts import MARKET_EVENT_COLUMNS
from asqt.db import initialize_database, query_all, table_columns
from asqt.events import (
    EVENT_TYPE_HOLDER_INCREASE,
    events_asof,
    holder_net_in_window,
    import_events_from_json,
    normalize_holder_trade_row,
    pull_holder_trade_events,
    query_events,
    upsert_events,
)
from asqt.provider_registry import provider_provides, providers_for
from asqt.records import RECORD_SCHEMAS
from asqt.strategies import (
    STOCK_HOLDER_INCREASE_FOLLOW,
    STRATEGY_SPECS,
    factor_specs_for,
    selector_rules_for,
    weights_for,
)


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


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_events.json"


def _wait_events_pull(client: TestClient, run_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/events/pull/{run_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("status") in {"success", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"events pull {run_id} did not finish: {last}")


def _bar(symbol: str, trade_date: str, close: float, *, volume: float = 1_000_000.0) -> dict:
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "amount": close * volume,
        "adj_factor": 1.0,
        "vwap": close,
    }


def _rising_series(symbol: str, start: str, days: int, start_px: float = 10.0) -> list[dict]:
    """Build consecutive calendar-day bars with rising prices (positive momentum)."""
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    rows = []
    for i in range(days):
        day = (d0 + timedelta(days=i)).isoformat()
        rows.append(_bar(symbol, day, start_px * (1.0 + 0.01 * i)))
    return rows


def _falling_series(symbol: str, start: str, days: int, start_px: float = 10.0) -> list[dict]:
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    rows = []
    for i in range(days):
        day = (d0 + timedelta(days=i)).isoformat()
        rows.append(_bar(symbol, day, start_px * (1.0 - 0.01 * i)))
    return rows


def test_market_event_schema_registered():
    assert "market_event" in RECORD_SCHEMAS
    assert RECORD_SCHEMAS["market_event"]["pk"] == ("event_id",)
    assert tuple(RECORD_SCHEMAS["market_event"]["columns"]) == MARKET_EVENT_COLUMNS
    assert providers_for("market_event") == ["tushare"]
    assert provider_provides("tushare", "market_event") is True
    assert provider_provides("baostock", "market_event") is False


def test_sqlite_market_event_table(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    cols = table_columns("market_event", settings=settings)
    assert set(MARKET_EVENT_COLUMNS) <= set(cols)


def test_events_asof_no_lookahead(tmp_path: Path):
    settings = make_settings(tmp_path)
    import_events_from_json(FIXTURE, settings=settings)
    all_rows = query_events(settings=settings, newest_first=False)
    assert len(all_rows) == 4
    asof = events_asof(all_rows, "2024-01-12")
    dates = {row["event_date"] for row in asof}
    assert dates == {"2024-01-05", "2024-01-10"}
    assert all(row["event_date"] <= "2024-01-12" for row in asof)
    via_query = query_events(settings=settings, asof="2024-01-12", newest_first=False)
    assert {row["event_id"] for row in via_query} == {row["event_id"] for row in asof}
    assert "fixture-holder-inc-600000-2024-02-01" not in {row["event_id"] for row in via_query}


def test_fixture_import_writes_parquet_and_sqlite(tmp_path: Path):
    settings = make_settings(tmp_path)
    result = import_events_from_json(FIXTURE, settings=settings)
    assert result["imported"] == 4
    assert Path(result["parquet"]).exists()
    db_rows = query_all(
        "SELECT event_id, event_type FROM market_event ORDER BY event_date",
        settings=settings,
    )
    assert len(db_rows) == 4
    assert {row["event_type"] for row in db_rows} == {"holder_increase", "holder_decrease"}
    import_events_from_json(FIXTURE, settings=settings)
    assert len(query_events(settings=settings)) == 4


def test_normalize_holder_trade_signs_value():
    inc = normalize_holder_trade_row(
        {
            "ts_code": "000001.SZ",
            "ann_date": "20240108",
            "holder_name": "Alice",
            "in_de": "IN",
            "change_vol": 1000,
        }
    )
    assert inc["event_type"] == EVENT_TYPE_HOLDER_INCREASE
    assert inc["event_date"] == "2024-01-08"
    assert inc["value"] == 1000.0
    dec = normalize_holder_trade_row(
        {
            "ts_code": "000001.SZ",
            "ann_date": "20240109",
            "holder_name": "Bob",
            "in_de": "DE",
            "change_vol": 500,
        }
    )
    assert dec["event_type"] == "holder_decrease"
    assert dec["value"] == -500.0


class FakeTushareEvents:
    source_id = "tushare"
    last_errors: list[dict[str, str]] = []

    def fetch_stk_holdertrade(self, symbols=None, start=None, end=None, *, trade_type=None):
        return [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20240301",
                "holder_name": "Mock Holder",
                "holder_type": "P",
                "in_de": "IN",
                "change_vol": 12345,
                "change_ratio": 0.1,
                "after_share": None,
                "after_ratio": None,
                "avg_price": 10.5,
                "total_share": None,
                "begin_date": "20240220",
                "close_date": "20240228",
            }
        ]


def test_pull_holder_trade_events_mocked(tmp_path: Path):
    settings = make_settings(tmp_path)
    result = pull_holder_trade_events(
        symbols=["000001.SZ"],
        start="2024-02-01",
        end="2024-03-31",
        settings=settings,
        adapter=FakeTushareEvents(),
    )
    assert result["upserted"] == 1
    assert result["fetched"] == 1
    assert result["unique_in_batch"] == 1
    assert result["stored_total"] >= 1
    rows = query_events(settings=settings, symbol="000001.SZ")
    assert len(rows) == 1
    assert rows[0]["event_type"] == "holder_increase"
    assert rows[0]["source"] == "tushare"
    assert rows[0]["value"] == 12345.0


def test_api_events_import_query_types_and_pull(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)

    client = TestClient(create_app())

    imported = client.post("/api/events/import", json={"path": str(FIXTURE)})
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 4

    listed = client.get("/api/events", params={"asof": "2024-01-12"})
    assert listed.status_code == 200
    listed_body = listed.json()
    listed_items = listed_body["items"] if isinstance(listed_body, dict) else listed_body
    assert len(listed_items) == 2
    assert listed_body["total"] == 2

    fuzzy = client.get("/api/events", params={"symbol": "000001", "page_size": 10})
    assert fuzzy.status_code == 200
    fuzzy_body = fuzzy.json()
    assert fuzzy_body["total"] >= 1
    assert all("000001" in row["symbol"] for row in fuzzy_body["items"])
    assert fuzzy_body["page_size"] == 10

    types = client.get("/api/events/types")
    assert types.status_code == 200
    assert set(types.json()) == {"holder_decrease", "holder_increase"}

    class Adapter:
        source_id = "tushare"
        last_errors = []

        def fetch_stk_holdertrade(self, symbols=None, start=None, end=None, *, trade_type=None):
            return [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20240310",
                    "holder_name": "API Mock",
                    "in_de": "DE",
                    "change_vol": 99,
                }
            ]

    monkeypatch.setattr(
        "asqt.adapters.tushare_source.TushareAdapter",
        lambda *a, **k: Adapter(),
    )
    pulled = client.post(
        "/api/events/pull",
        json={"symbols": ["000001.SZ"], "start": "2024-03-01", "end": "2024-03-31"},
    )
    assert pulled.status_code == 200, pulled.text
    job = pulled.json()
    assert job.get("run_id")
    done = _wait_events_pull(client, job["run_id"])
    assert done["status"] == "success"
    assert done["result"]["upserted"] == 1
    assert done["result"]["persisted"]["sqlite"] == "market_event"

    bad = client.post("/api/events/pull", json={"source": "baostock"})
    assert bad.status_code == 400


def test_upsert_events_generates_stable_id(tmp_path: Path):
    settings = make_settings(tmp_path)
    row = {
        "event_type": "holder_increase",
        "symbol": "000001.SZ",
        "event_date": "2024-05-01",
        "actor": "X",
        "value": 10,
        "source": "fixture",
    }
    upsert_events([row], settings=settings)
    upsert_events([row], settings=settings)
    rows = query_events(settings=settings)
    assert len(rows) == 1
    assert rows[0]["event_id"]


def test_holder_net_in_window_no_lookahead():
    events = [
        {
            "event_type": "holder_increase",
            "symbol": "000001.SZ",
            "event_date": "2024-01-05",
            "value": 100.0,
        },
        {
            "event_type": "holder_increase",
            "symbol": "000001.SZ",
            "event_date": "2024-02-01",
            "value": 999.0,
        },
    ]
    assert holder_net_in_window(events, "000001.SZ", "2024-01-12", 20) == 100.0
    assert holder_net_in_window(events, "000001.SZ", "2024-01-04", 20) is None


def test_stock_holder_increase_follow_registered_as_draft():
    assert STOCK_HOLDER_INCREASE_FOLLOW in STRATEGY_SPECS
    spec = STRATEGY_SPECS[STOCK_HOLDER_INCREASE_FOLLOW]
    assert spec["default_lifecycle"] == "draft"
    assert spec["instrument_type"] == "stock"
    assert spec["params"]["event_lookback"] == 20
    assert "min_momentum" in spec["params"]
    rules = selector_rules_for(STOCK_HOLDER_INCREASE_FOLLOW)
    assert rules["score_factor"] == "stock_holder_net"
    assert any(f["factor"] == "stock_holder_net" and f["op"] == ">" for f in rules["filters"])
    names = {s["name"] for s in factor_specs_for(STOCK_HOLDER_INCREASE_FOLLOW, events=[])}
    assert names == {"stock_holder_net", "stock_momentum"}


def test_stock_holder_increase_follow_weights_from_fixture_no_lookahead(tmp_path: Path):
    settings = make_settings(tmp_path)
    import_events_from_json(FIXTURE, settings=settings)
    events = query_events(settings=settings, newest_first=False)

    # Rising prices so default min_momentum=0 passes for both names.
    market = (
        _rising_series("000001.SZ", "2023-12-20", 40)
        + _rising_series("000002.SZ", "2023-12-20", 40)
        + _rising_series("600000.SH", "2023-12-20", 50)
    )
    params = {
        "event_lookback": 30,
        "lookback": 5,
        "min_momentum": 0.0,
        "top_k": 5,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    }

    before = weights_for(
        STOCK_HOLDER_INCREASE_FOLLOW,
        market,
        "2024-01-04",
        params=params,
        events=events,
        settings=settings,
    )
    assert before == {}

    mid = weights_for(
        STOCK_HOLDER_INCREASE_FOLLOW,
        market,
        "2024-01-12",
        params=params,
        events=events,
        settings=settings,
    )
    assert set(mid) == {"000001.SZ", "000002.SZ"}
    assert "600000.SH" not in mid
    # equal weight clipped by max_weight 0.10 each → 0.10+0.10
    assert mid["000001.SZ"] == 0.1
    assert mid["000002.SZ"] == 0.1

    # Future Feb event must not leak into January asof.
    late_jan = weights_for(
        STOCK_HOLDER_INCREASE_FOLLOW,
        market,
        "2024-01-31",
        params=params,
        events=events,
        settings=settings,
    )
    assert "600000.SH" not in late_jan


def test_stock_holder_increase_follow_momentum_filter(tmp_path: Path):
    settings = make_settings(tmp_path)
    events = [
        {
            "event_type": "holder_increase",
            "symbol": "000001.SZ",
            "event_date": "2024-01-05",
            "value": 1_000_000.0,
            "source": "fixture",
        },
        {
            "event_type": "holder_increase",
            "symbol": "000002.SZ",
            "event_date": "2024-01-05",
            "value": 2_000_000.0,
            "source": "fixture",
        },
    ]
    market = _rising_series("000001.SZ", "2023-12-20", 30) + _falling_series(
        "000002.SZ", "2023-12-20", 30
    )
    params = {
        "event_lookback": 20,
        "lookback": 5,
        "min_momentum": 0.0,
        "top_k": 5,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    }
    weights = weights_for(
        STOCK_HOLDER_INCREASE_FOLLOW,
        market,
        "2024-01-12",
        params=params,
        events=events,
        settings=settings,
    )
    assert set(weights) == {"000001.SZ"}

    # Disable momentum filter → both names with net increase survive.
    loose = dict(params)
    loose["min_momentum"] = None
    both = weights_for(
        STOCK_HOLDER_INCREASE_FOLLOW,
        market,
        "2024-01-12",
        params=loose,
        events=events,
        settings=settings,
    )
    assert set(both) == {"000001.SZ", "000002.SZ"}
