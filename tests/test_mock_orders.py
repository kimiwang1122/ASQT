from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.bootstrap import seed_demo
from asqt.config import Settings
from asqt.db import execute
from asqt.orders import MockOrderService


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


def _client(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    seed_demo(settings)
    monkeypatch.setenv("ASQT_DATA_DIR", str(settings.data_dir))
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    return TestClient(create_app()), settings


def test_mock_order_accepted_when_no_quality_block(tmp_path, monkeypatch):
    client, _settings = _client(tmp_path, monkeypatch)
    result = client.post("/api/orders/mock", json={"symbol": "000001.SZ", "quantity": 100})
    assert result.status_code == 200
    body = result.json()
    assert body["accepted"] is True
    assert body["order"]["status"] == "risk_pending"
    listed = client.get("/api/orders")
    assert listed.json()[0]["symbol"] == "000001.SZ"


def test_mock_order_rejected_when_quality_block_open(tmp_path, monkeypatch):
    client, settings = _client(tmp_path, monkeypatch)
    execute(
        """
        INSERT INTO quality_issue
            (issue_id, dataset, symbol, trade_date, check_type, severity, status, diff)
        VALUES ('blk-1', 'market_daily', '000001.SZ', '2026-08-21', 'missing', 'block', 'open', 'mock-block')
        """,
        settings=settings,
    )
    gate = MockOrderService(settings).quality_gate()
    assert gate["trade_allowed"] is False
    result = client.post("/api/orders/mock", json={"symbol": "510300.SH", "side": "BUY", "quantity": 200})
    body = result.json()
    assert body["accepted"] is False
    assert body["reason"] == "quality_block"
    assert body["order"]["status"] == "rejected"
    assert body["quality"]["block_count"] == 1
