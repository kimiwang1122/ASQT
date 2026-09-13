from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.bootstrap import seed_demo
from asqt.config import Settings
from asqt.storage import upsert_market_daily
from asqt.symbols import split_symbol


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


def test_split_symbol_separates_code_and_exchange():
    assert split_symbol("000001.SZ") == ("000001", "SZ")
    assert split_symbol("510300.SH") == ("510300", "SH")


def test_market_snapshot_is_volume_topn_with_filters_and_volume_marks(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    seed_demo(settings)
    upsert_market_daily(
        [
            {
                "symbol": "000001.SZ",
                "trade_date": "2025-08-21",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 50000000,
                "amount": 500000000.0,
                "adj_factor": 1.0,
                "source": "demo",
                "version": "demo-yoy",
            }
        ],
        settings=settings,
    )

    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)

    client = TestClient(create_app())
    default = client.get("/api/market/snapshot")
    assert default.status_code == 200
    body = default.json()
    assert body["trade_date"] == "2026-08-21"
    assert body["returned"] == 2
    assert body["limit"] == 50
    assert [row["symbol"] for row in body["items"]] == ["510300.SH", "000001.SZ"]
    ping_an = body["items"][1]
    assert ping_an["code"] == "000001"
    assert ping_an["exchange"] == "SZ"
    assert ping_an["name"] == "平安银行"
    assert ping_an["volume_dod_dir"] == "down"
    assert ping_an["volume_dod"] == pytest.approx((103000000 - 124000000) / 124000000)
    assert ping_an["volume_yoy_dir"] == "up"
    assert ping_an["volume_yoy"] == pytest.approx((103000000 - 50000000) / 50000000)

    sz_only = client.get("/api/market/snapshot", params={"exchange": "SZ", "limit": 50})
    assert [row["exchange"] for row in sz_only.json()["items"]] == ["SZ"]

    by_code = client.get("/api/market/snapshot", params={"code": "00000"})
    assert by_code.json()["returned"] == 1
    assert by_code.json()["items"][0]["code"] == "000001"

    by_name = client.get("/api/market/snapshot", params={"code": "平安"})
    assert by_name.json()["items"][0]["code"] == "000001"

    etf_only = client.get("/api/market/snapshot", params={"instrument_type": "etf"})
    assert etf_only.json()["items"][0]["instrument_type"] == "etf"

    top1 = client.get("/api/market/snapshot", params={"limit": 1})
    assert top1.json()["returned"] == 1
    assert top1.json()["items"][0]["symbol"] == "510300.SH"

    dod_asc = client.get("/api/market/snapshot", params={"sort": "dod", "order": "asc"})
    assert dod_asc.json()["sort"] == "dod"
    assert dod_asc.json()["items"][0]["symbol"] == "000001.SZ"


def test_gate_d1_snapshot_asof_data_version_deterministic(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    seed_demo(settings)

    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())

    first = client.get("/api/market/snapshot", params={"asof": "2026-08-21", "limit": 10})
    second = client.get("/api/market/snapshot", params={"asof": "2026-08-21", "limit": 10})
    assert first.status_code == 200
    assert first.json() == second.json()
    body = first.json()
    assert body["asof"] == "2026-08-21"
    assert body["trade_date"] == "2026-08-21"
    assert body["data_version"]
    assert body["version_mismatch"] is False

    same_via_trade_date = client.get(
        "/api/market/snapshot",
        params={"trade_date": "2026-08-21", "limit": 10},
    )
    assert same_via_trade_date.json() == body

    pinned = client.get(
        "/api/market/snapshot",
        params={"asof": "2026-08-21", "data_version": body["data_version"], "limit": 10},
    )
    assert pinned.json() == body

    mismatch = client.get(
        "/api/market/snapshot",
        params={"asof": "2026-08-21", "data_version": "deadbeefdeadbeef", "limit": 10},
    )
    assert mismatch.status_code == 200
    bad = mismatch.json()
    assert bad["version_mismatch"] is True
    assert bad["items"] == []
    assert bad["data_version"] == body["data_version"]
