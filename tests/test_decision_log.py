"""GATE-C1: decision_log pending → resolved with PIT asof filtering."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.db import initialize_database, query_all
from asqt.decision_log import list_decisions, record_pending, resolve_for_session
from asqt.paper import PaperOrderService
from asqt.strategies import STOCK_MOMENTUM_TOPK
from asqt.storage import read_market_daily
from tests.test_p2_research import make_settings
from tests.test_p3_paper import _prepare


def test_gate_c1_schema_and_pending_resolve(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    pending = record_pending(
        strategy_id="stock_momentum_topk",
        signal_date="2024-01-08",
        weights={"000001.SZ": 0.2, "000002.SZ": 0.1},
        strategy_version="v1",
        data_version="dv1",
        settings=settings,
    )
    assert pending["status"] == "pending"
    assert pending["thesis"]["weights"]["000001.SZ"] == 0.2
    assert not pending.get("lesson")
    # Structured JSON only — no markdown blob as primary store
    raw = query_all(
        "SELECT thesis_json, outcome_json FROM decision_log WHERE decision_id = ?",
        (pending["decision_id"],),
        settings=settings,
    )[0]
    assert raw["thesis_json"].startswith("{")
    assert raw["outcome_json"] is None

    again = record_pending(
        strategy_id="stock_momentum_topk",
        signal_date="2024-01-08",
        weights={"000001.SZ": 0.25},
        settings=settings,
    )
    assert again["decision_id"] == pending["decision_id"]

    resolved = resolve_for_session(
        strategy_id="stock_momentum_topk",
        signal_date="2024-01-08",
        fill_date="2024-01-09",
        nav_before=1_000_000.0,
        nav_after=1_010_000.0,
        halted=False,
        order_ids=["o1"],
        settings=settings,
    )
    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["fill_date"] == "2024-01-09"
    assert resolved["outcome"]["session_return"] == pytest.approx(0.01)
    assert "未触发急停" in (resolved["lesson"] or "")


def test_gate_c1_asof_hides_future_and_unresolved_lessons(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    early = record_pending(
        strategy_id="s1",
        signal_date="2024-01-05",
        weights={"000001.SZ": 0.1},
        settings=settings,
    )
    record_pending(
        strategy_id="s1",
        signal_date="2024-01-10",
        weights={"000001.SZ": 0.1},
        settings=settings,
    )

    asof_day = list_decisions(strategy_id="s1", asof="2024-01-05", settings=settings)
    assert {row["decision_id"] for row in asof_day} == {early["decision_id"]}
    assert asof_day[0]["status"] == "pending"

    resolve_for_session(
        strategy_id="s1",
        signal_date="2024-01-05",
        fill_date="2024-01-06",
        nav_before=100.0,
        nav_after=101.0,
        settings=settings,
    )
    # Resolved lesson must not leak before resolved_at
    assert list_decisions(strategy_id="s1", asof="2024-01-05", settings=settings) == []

    record_pending(
        strategy_id="s1",
        signal_date="2024-01-07",
        weights={"000002.SZ": 0.2},
        settings=settings,
    )
    asof_mid = {
        row["signal_date"]: row
        for row in list_decisions(strategy_id="s1", asof="2024-01-07", settings=settings)
    }
    assert asof_mid["2024-01-05"]["status"] == "resolved"
    assert asof_mid["2024-01-07"]["status"] == "pending"
    assert "2024-01-10" not in asof_mid


def test_gate_c1_paper_attaches_decision_id_and_resolves(tmp_path: Path):
    settings, _engine, _service = _prepare(tmp_path)
    rows = read_market_daily(settings=settings)
    dates = sorted({str(r["trade_date"]) for r in rows})
    assert len(dates) >= 3
    signal = dates[-2]
    fill = dates[-1]

    PaperOrderService(settings).build_orders(
        fill, STOCK_MOMENTUM_TOPK, signal_date=signal, apply_fills=True
    )

    targets = query_all(
        "SELECT DISTINCT decision_id FROM target_position WHERE strategy_id = ? AND trade_date = ?",
        (STOCK_MOMENTUM_TOPK, signal),
        settings=settings,
    )
    assert targets and targets[0]["decision_id"]

    matched = [
        d
        for d in list_decisions(strategy_id=STOCK_MOMENTUM_TOPK, settings=settings)
        if d["signal_date"] == signal
    ]
    assert matched
    assert matched[0]["status"] == "resolved"
    assert matched[0]["outcome"] is not None
    assert "session_return" in matched[0]["outcome"]

    orders = query_all(
        """
        SELECT decision_id FROM standard_order
        WHERE strategy_id = ? AND trade_date = ? AND decision_id IS NOT NULL
        LIMIT 1
        """,
        (STOCK_MOMENTUM_TOPK, fill),
        settings=settings,
    )
    if orders:
        assert orders[0]["decision_id"] == matched[0]["decision_id"]


def test_gate_c1_api_lists_decisions(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    record_pending(
        strategy_id="stock_momentum_topk",
        signal_date="2024-01-08",
        weights={"000001.SZ": 0.2},
        settings=settings,
    )
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    resp = client.get("/api/decisions", params={"strategy_id": "stock_momentum_topk", "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert body["items"][0]["status"] == "pending"
    assert body["items"][0]["thesis"]["weights"]["000001.SZ"] == 0.2
