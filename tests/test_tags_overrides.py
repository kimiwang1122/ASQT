"""Focused tests for symbol_tag pools and paper_override → target_position."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.db import execute, initialize_database, query_all
from asqt.overrides import apply_overrides, upsert_override
from asqt.research_engine import LocalResearchEngine, LocalStrategyService
from asqt.strategies import STOCK_MOMENTUM_TOPK, STRATEGY_SPECS
from asqt.tags import UNIVERSE_CSV_SOURCE, resolve_pool
from asqt.universe import apply_universe
from tests.test_p1_universe import _etf, _stock, _write_csv
from tests.test_p2_research import _seed, _trend_book, make_settings


def test_apply_universe_syncs_symbol_tags(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    stocks = [_stock(symbol=f"{i:03d}001.SZ", name=f"S{i}", pool="hs300" if i < 25 else "csi500") for i in range(50)]
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
    assert result["tags"] == 55
    tags = query_all(
        "SELECT tag, symbol, source FROM symbol_tag WHERE source = ? ORDER BY tag, symbol",
        (UNIVERSE_CSV_SOURCE,),
        settings=settings,
    )
    assert len(tags) == 55
    assert all(row["source"] == UNIVERSE_CSV_SOURCE for row in tags)
    assert "000001.SZ" in resolve_pool(["hs300"], settings=settings)
    assert "025001.SZ" in resolve_pool(["csi500"], settings=settings)
    assert "510300.SH" in resolve_pool(["etf_broad"], settings=settings)


def test_force_out_removes_symbol_from_targets(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    engine = LocalResearchEngine(settings)
    report = engine.run_backtest(
        STOCK_MOMENTUM_TOPK, STRATEGY_SPECS[STOCK_MOMENTUM_TOPK]["parameter_set_id"], "auto"
    )
    assert report["ok"] is True
    execute(
        "UPDATE strategy_version SET status = 'paper' WHERE strategy_id = ?",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    asof = sorted({row["trade_date"] for row in rows})[-2]
    baseline = LocalStrategyService(settings).generate_target_positions(STOCK_MOMENTUM_TOPK, asof)
    assert baseline
    victim = baseline[0]["symbol"]
    upsert_override(
        strategy_id=STOCK_MOMENTUM_TOPK,
        symbol=victim,
        action="force_out",
        reason="test exclude",
        settings=settings,
    )
    targets = LocalStrategyService(settings).generate_target_positions(STOCK_MOMENTUM_TOPK, asof)
    symbols = {item["symbol"] for item in targets}
    assert victim not in symbols
    audits = query_all(
        "SELECT action, target_type FROM operation_audit WHERE target_type = 'paper_override'",
        settings=settings,
    )
    assert any(row["action"] == "apply" for row in audits)


def test_apply_overrides_force_in_and_cap(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    upsert_override(
        strategy_id="demo",
        symbol="000001.SZ",
        action="force_in",
        weight=0.2,
        settings=settings,
    )
    upsert_override(
        strategy_id="demo",
        symbol="000002.SZ",
        action="cap",
        weight=0.1,
        settings=settings,
    )
    weights, reasons = apply_overrides(
        {"000002.SZ": 0.5, "000003.SZ": 0.3},
        "demo",
        settings=settings,
        audit=False,
    )
    assert weights["000001.SZ"] == pytest.approx(0.2)
    assert weights["000002.SZ"] == pytest.approx(0.1)
    assert weights["000003.SZ"] == pytest.approx(0.3)
    assert reasons["000001.SZ"] == "override:force_in"
    assert reasons["000002.SZ"] == "override:cap"


def test_draft_still_cannot_emit_with_overrides(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    upsert_override(
        strategy_id=STOCK_MOMENTUM_TOPK,
        symbol="000001.SZ",
        action="force_in",
        weight=0.1,
        settings=settings,
    )
    service = LocalStrategyService(settings)
    with pytest.raises(PermissionError):
        service.generate_target_positions(STOCK_MOMENTUM_TOPK, rows[-1]["trade_date"])


def test_tags_and_overrides_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())

    posted = client.post(
        "/api/tags",
        json={"rows": [{"tag": "hs300", "symbol": "000001.SZ", "source": "manual", "note": "n"}]},
    )
    assert posted.status_code == 200
    assert posted.json()[0]["symbol"] == "000001.SZ"
    listed = client.get("/api/tags", params={"tag": "hs300"})
    assert listed.status_code == 200
    assert listed.json()[0]["symbol"] == "000001.SZ"
    pool = client.get("/api/pools/hs300")
    assert pool.status_code == 200
    assert {row["symbol"] for row in pool.json()} == {"000001.SZ"}

    put = client.put(
        "/api/paper/overrides",
        json={
            "strategy_id": STOCK_MOMENTUM_TOPK,
            "symbol": "000001.SZ",
            "action": "force_out",
            "reason": "api test",
        },
    )
    assert put.status_code == 200
    assert put.json()["action"] == "force_out"
    got = client.get("/api/paper/overrides", params={"strategy_id": STOCK_MOMENTUM_TOPK})
    assert got.status_code == 200
    assert len(got.json()) == 1
    deleted = client.delete(
        "/api/paper/overrides",
        params={"strategy_id": STOCK_MOMENTUM_TOPK, "symbol": "000001.SZ"},
    )
    assert deleted.status_code == 200
    assert client.get("/api/paper/overrides", params={"strategy_id": STOCK_MOMENTUM_TOPK}).json() == []
