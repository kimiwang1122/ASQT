"""GATE-E1 fundamental_snapshot schema + ann_date PIT; GATE-E2 draft assistant."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.contracts import FUNDAMENTAL_SNAPSHOT_COLUMNS
from asqt.db import execute, initialize_database, query_all
from asqt.draft_assistant import DraftWriteForbidden, analyze_readonly
from asqt.fundamentals import fundamentals_asof
from asqt.provider_registry import provider_provides, providers_for
from asqt.records import RECORD_SCHEMAS, upsert_records
from asqt.strategies import STOCK_MOMENTUM_TOPK, STRATEGY_SPECS
from tests.test_p2_research import make_settings
from tests.test_p3_paper import _prepare


def test_gate_e1_fundamental_schema_and_ann_date_pit(tmp_path: Path):
    assert "fundamental_snapshot" in RECORD_SCHEMAS
    assert RECORD_SCHEMAS["fundamental_snapshot"]["columns"] == FUNDAMENTAL_SNAPSHOT_COLUMNS
    assert provider_provides("tushare", "fundamental_snapshot")
    assert providers_for("fundamental_snapshot") == ["tushare"]

    settings = make_settings(tmp_path)
    initialize_database(settings)
    rows = [
        {
            "symbol": "000001.SZ",
            "report_period": "2023-12-31",
            "ann_date": "2024-03-15",
            "asof_date": "2024-03-15",
            "metric": "roe",
            "value": 0.12,
            "unit": "ratio",
            "source": "fixture",
            "version": "v1",
        },
        {
            "symbol": "000001.SZ",
            "report_period": "2024-03-31",
            "ann_date": "2024-04-20",
            "asof_date": "2024-04-20",
            "metric": "roe",
            "value": 0.13,
            "unit": "ratio",
            "source": "fixture",
            "version": "v1",
        },
    ]
    path = upsert_records("fundamental_snapshot", rows, settings=settings)
    assert path.exists()

    visible = fundamentals_asof(rows, "2024-03-15")
    assert len(visible) == 1
    assert visible[0]["ann_date"] == "2024-03-15"
    assert fundamentals_asof(rows, "2024-03-14") == []
    later = fundamentals_asof(rows, "2024-04-20")
    assert len(later) == 2


def test_gate_e2_draft_assist_readonly_no_targets(tmp_path: Path, monkeypatch):
    settings, _engine, _service = _prepare(tmp_path)
    # Ensure a draft strategy exists (holder follow is draft by default after seed? use explicit)
    rows = query_all(
        "SELECT status FROM strategy_version WHERE strategy_id = ? ORDER BY created_at DESC LIMIT 1",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    assert rows and rows[0]["status"] == "paper"

    with pytest.raises(DraftWriteForbidden):
        analyze_readonly(
            asof="2024-06-01",
            symbols=["000001.SZ"],
            strategy_id=STOCK_MOMENTUM_TOPK,
            settings=settings,
        )

    # Seed a draft-only strategy version
    execute(
        """
        INSERT OR REPLACE INTO strategy_version
            (strategy_id, version, status, parameter_set_id, code_version, risk_config, effective_date)
        VALUES ('draft_probe', 'v0', 'draft', ?, 'test', 'docs/p0/risk_defaults.md', '2024-01-01')
        """,
        (STRATEGY_SPECS[STOCK_MOMENTUM_TOPK]["parameter_set_id"],),
        settings=settings,
    )

    before = query_all("SELECT COUNT(*) AS c FROM target_position", settings=settings)[0]["c"]
    result = analyze_readonly(
        asof="2024-06-01",
        symbols=["000001.SZ"],
        strategy_id="draft_probe",
        settings=settings,
    )
    assert result["writable"] is False
    assert result["emits_targets"] is False
    assert result["decision_id"]
    after = query_all("SELECT COUNT(*) AS c FROM target_position", settings=settings)[0]["c"]
    assert after == before

    thesis = query_all(
        "SELECT thesis_json FROM decision_log WHERE decision_id = ?",
        (result["decision_id"],),
        settings=settings,
    )[0]["thesis_json"]
    assert "draft_assistant" in thesis

    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    denied = client.post(
        "/api/research/draft-assist",
        json={"asof": "2024-06-01", "symbols": ["000001.SZ"], "strategy_id": STOCK_MOMENTUM_TOPK},
    )
    assert denied.status_code == 403
    ok = client.post(
        "/api/research/draft-assist",
        json={"asof": "2024-06-01", "symbols": ["000001.SZ"], "strategy_id": "draft_probe"},
    )
    assert ok.status_code == 200
    assert ok.json()["writable"] is False
