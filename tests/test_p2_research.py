from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asqt.api import create_app
from asqt.config import Settings
from asqt.db import execute, initialize_database, query_all
from asqt.research_engine import LocalResearchEngine, LocalStrategyService, data_version_for
from asqt.storage import write_market_daily
from asqt.strategies import (
    ETF_MA_ROTATE,
    ETF_MOMENTUM_TOPK,
    STOCK_MOMENTUM_TOPK,
    STRATEGY_SPECS,
    asof_rows,
    market_by_symbol,
    signal_etf_momentum_topk,
    signal_stock_momentum_topk,
    suspended_keys,
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


def _dates(n: int, start: str = "2024-01-02") -> list[str]:
    cursor = date.fromisoformat(start)
    out: list[str] = []
    while len(out) < n:
        if cursor.weekday() < 5:
            out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def _bar(symbol: str, trade_date: str, close: float, adj: float = 1.0) -> dict:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000,
        "amount": close * 1000,
        "adj_factor": adj,
        "source": "test",
        "version": "p2-fixture",
    }


def _seed(settings: Settings, rows: list[dict], instruments: list[tuple[str, str]]) -> None:
    initialize_database(settings)
    write_market_daily(rows, settings=settings)
    execute("DELETE FROM instrument_master", settings=settings)
    for symbol, kind in instruments:
        execute(
            """
            INSERT INTO instrument_master
                (symbol, name, instrument_type, exchange, board, list_date, status, is_st)
            VALUES (?, ?, ?, ?, ?, ?, 'listed', 0)
            """,
            (symbol, symbol, kind, symbol.split(".")[-1], "main" if kind == "stock" else "broad_index", "2020-01-01"),
            settings=settings,
        )
    dates = sorted({row["trade_date"] for row in rows})
    for trade_date in dates:
        execute(
            """
            INSERT OR REPLACE INTO trade_calendar
                (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
            VALUES (?, 'CN', 1, '09:30', '15:00', NULL, NULL)
            """,
            (trade_date,),
            settings=settings,
        )


def _trend_book() -> tuple[list[dict], list[tuple[str, str]]]:
    days = _dates(60)
    rows: list[dict] = []
    stocks = ["000001.SZ", "000002.SZ", "000063.SZ", "000100.SZ", "000333.SZ", "000338.SZ"]
    etfs = ["510300.SH", "510500.SH", "159915.SZ"]
    for index, day in enumerate(days):
        for offset, symbol in enumerate(stocks):
            rows.append(_bar(symbol, day, 10 + offset + index * (0.2 + offset * 0.05)))
        for offset, symbol in enumerate(etfs):
            rows.append(_bar(symbol, day, 2 + offset * 0.1 + (0.03 if index > 15 else -0.02) * index))
    instruments = [(symbol, "stock") for symbol in stocks] + [(symbol, "etf") for symbol in etfs]
    return rows, instruments


def test_p2_both_strategies_backtest_isolated_and_reproducible(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    engine = LocalResearchEngine(settings)
    version = data_version_for(rows)

    first = {}
    second = {}
    for strategy_id in (ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK):
        params = STRATEGY_SPECS[strategy_id]["parameter_set_id"]
        first[strategy_id] = engine.run_backtest(strategy_id, params, version)
        second[strategy_id] = engine.run_backtest(strategy_id, params, version)

    for strategy_id, report in first.items():
        assert report["ok"] is True
        assert report["status"] == "candidate"
        assert report["t_plus_one"] is True
        assert report["kind"] in {"rule", "topk"}
        assert report["metrics"]["is"]["n_days"] >= 1
        assert report["metrics"]["oos"]["n_days"] >= 1
        is_ret = report["metrics"]["is"]["total_return"]
        oos_ret = report["metrics"]["oos"]["total_return"]
        assert abs((1.0 + is_ret) * (1.0 + oos_ret) - report["nav"]) < 1e-8
        assert report["in_sample_end"] < max(row["trade_date"] for row in rows)
        assert second[strategy_id]["metrics"] == report["metrics"]
        assert second[strategy_id]["data_version"] == report["data_version"]
        assert second[strategy_id]["last_weights"] == report["last_weights"]

    kinds = {first[ETF_MA_ROTATE]["kind"], first[STOCK_MOMENTUM_TOPK]["kind"]}
    assert kinds == {"rule", "topk"}

    versions = {row["strategy_id"]: row["status"] for row in engine.strategies.list_versions()}
    assert versions[ETF_MA_ROTATE] == "candidate"
    assert versions[STOCK_MOMENTUM_TOPK] == "candidate"
    factors = query_all("SELECT DISTINCT factor_name FROM factor_signal", settings=settings)
    assert {row["factor_name"] for row in factors} == {"etf_ma_gap", "stock_momentum"}
    assert (settings.experiment_dir / f"latest-{ETF_MA_ROTATE}.json").exists()


def test_p2_etf_momentum_topk_prefers_stronger_etf(tmp_path):
    days = _dates(50)
    rows = []
    for index, day in enumerate(days):
        rows.append(_bar("510300.SH", day, 4.0 + index * 0.01))
        rows.append(_bar("510500.SH", day, 5.0 + index * 0.05))
        rows.append(_bar("159915.SZ", day, 2.0 + index * 0.02))
        rows.append(_bar("000001.SZ", day, 10.0 + index))  # stock must be ignored
    weights = signal_etf_momentum_topk(rows, days[-1])
    assert set(weights) <= {"510300.SH", "510500.SH", "159915.SZ"}
    assert "000001.SZ" not in weights
    assert len(weights) == 3
    assert abs(sum(weights.values()) - 0.60) < 1e-9


def test_p2_signal_cannot_see_future_close(tmp_path):
    days = _dates(25)
    rows = []
    tight = {"lookback": 5, "top_k": 1, "max_weight": 0.10, "gross_limit": 0.95}
    for index, day in enumerate(days[:-1]):
        rows.append(_bar("000001.SZ", day, 10.0 + index * 0.05))
        rows.append(_bar("000002.SZ", day, 10.0))
    rows.append(_bar("000001.SZ", days[-1], 10.0 + 23 * 0.05))
    rows.append(_bar("000002.SZ", days[-1], 40.0))
    asof = days[-2]
    weights = signal_stock_momentum_topk(rows, asof, params=tight)
    leaked = signal_stock_momentum_topk(rows, days[-1], params=tight)
    assert list(weights) == ["000001.SZ"]
    assert list(leaked) == ["000002.SZ"]


def test_p2_indexed_weights_match_full_scan(tmp_path):
    days = _dates(30)
    rows = []
    for index, day in enumerate(days):
        rows.append(_bar("510300.SH", day, 4.0 + index * 0.01))
        rows.append(_bar("510500.SH", day, 5.0 + (0.02 if index > 10 else 0.0)))
        rows.append(_bar("000001.SZ", day, 10.0 + index * 0.03))
        rows.append(_bar("000002.SZ", day, 8.0 + (0.2 if index % 3 == 0 else 0.0)))
    limits = [{"symbol": "000002.SZ", "trade_date": days[20], "is_suspended": 1}]
    grouped = market_by_symbol(rows)
    halted = suspended_keys(limits)
    asof = days[22]
    for strategy_id in (ETF_MA_ROTATE, STOCK_MOMENTUM_TOPK, ETF_MOMENTUM_TOPK):
        naive = weights_for(strategy_id, rows, asof, limits=limits)
        indexed = weights_for(
            strategy_id,
            rows,
            asof,
            limits=limits,
            market_by_symbol=grouped,
            suspended=halted,
        )
        assert indexed == naive


def test_p2_draft_cannot_emit_targets(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    service = LocalStrategyService(settings)
    with pytest.raises(PermissionError):
        service.generate_target_positions(STOCK_MOMENTUM_TOPK, rows[-1]["trade_date"])


def test_p2_paper_can_emit_targets_and_quality_fail_blocks_candidate(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    engine = LocalResearchEngine(settings)
    report = engine.run_backtest(STOCK_MOMENTUM_TOPK, STRATEGY_SPECS[STOCK_MOMENTUM_TOPK]["parameter_set_id"], "auto")
    assert report["status"] == "candidate"
    execute(
        "UPDATE strategy_version SET status = 'paper' WHERE strategy_id = ?",
        (STOCK_MOMENTUM_TOPK,),
        settings=settings,
    )
    asof = sorted({row["trade_date"] for row in rows})[-2]
    targets = engine.strategies.generate_target_positions(STOCK_MOMENTUM_TOPK, asof)
    assert targets
    assert all(item["data_version"] for item in targets)
    assert sum(item["target_weight"] for item in targets) <= 0.95 + 1e-9
    stored = query_all("SELECT * FROM target_position WHERE strategy_id = ?", (STOCK_MOMENTUM_TOPK,), settings=settings)
    assert stored

    rows[0]["high"] = 1
    rows[0]["low"] = 3
    write_market_daily(rows, settings=settings)
    failed = engine.run_backtest(ETF_MA_ROTATE, STRATEGY_SPECS[ETF_MA_ROTATE]["parameter_set_id"], "auto")
    assert failed["ok"] is False
    assert failed["status"] == "failed"
    assert query_all(
        "SELECT status FROM strategy_version WHERE strategy_id = ?",
        (ETF_MA_ROTATE,),
        settings=settings,
    )[0]["status"] == "failed"


def test_p2_ports_do_not_import_qlib():
    import asqt.research_engine as module
    import asqt.review as review
    import asqt.strategies as strategies

    assert "qlib" not in module.__dict__
    assert "qlib" not in review.__dict__
    assert "qlib" not in strategies.__dict__


def test_p2_backtest_attribution_and_quality_block(tmp_path):
    from asqt.review import LocalReviewService

    settings = make_settings(tmp_path)
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    engine = LocalResearchEngine(settings)
    report = engine.run_backtest(ETF_MA_ROTATE, STRATEGY_SPECS[ETF_MA_ROTATE]["parameter_set_id"], "auto")
    attr = LocalReviewService(settings).attribute_backtest(ETF_MA_ROTATE)
    assert attr["ok"] is True
    assert attr["paper_vs_backtest"]["available"] is False
    assert attr["paper_vs_backtest"]["reason"] == "no_paper_fills"
    assert abs(attr["nav"] - report["nav"]) < 1e-8
    assert attr["is_days"] >= 1
    assert attr["oos_days"] >= 1
    assert attr["sample"]["n_sessions"] >= 4
    assert attr["params"]
    assert attr["top_oos"] is not None
    assert abs(attr["is_contribution"] + attr["oos_contribution"] - attr["additive_return"]) < 1e-12
    assert attr["by_symbol"]
    assert attr["by_symbol"][0]["contribution"] >= attr["by_symbol"][-1]["contribution"]
    assert all(row["days"] >= 1 for row in attr["by_symbol"])

    execute(
        """
        INSERT INTO quality_issue
            (issue_id, dataset, symbol, trade_date, check_type, severity, status, diff)
        VALUES ('blk-attr', 'market_daily', '510300.SH', '2024-01-02', 'missing', 'block', 'open', 'test-block')
        """,
        settings=settings,
    )
    blocked = LocalReviewService(settings).attribute_backtest(ETF_MA_ROTATE)
    assert blocked["ok"] is False
    assert blocked["reason"] == "quality_block"
    assert blocked["by_symbol"] == []

    daily = LocalReviewService(settings).build_daily_review()
    assert daily["paper_vs_backtest"]["available"] is False
    assert len(daily["items"]) == len(STRATEGY_SPECS)


def test_p2_attribution_api(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    LocalResearchEngine(settings).run_backtest(
        STOCK_MOMENTUM_TOPK,
        STRATEGY_SPECS[STOCK_MOMENTUM_TOPK]["parameter_set_id"],
        "auto",
    )
    from asqt import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    versions = client.get("/api/strategies").json()
    assert any(row["strategy_id"] == STOCK_MOMENTUM_TOPK for row in versions)
    experiments = client.get("/api/research/experiments").json()
    assert any(row["strategy_id"] == STOCK_MOMENTUM_TOPK for row in experiments)
    attr = client.get("/api/research/attribution", params={"strategy_id": STOCK_MOMENTUM_TOPK}).json()
    assert attr["ok"] is True
    assert attr["by_symbol"]
    assert attr["paper_vs_backtest"]["available"] is False
    bad = client.get("/api/research/attribution", params={"strategy_id": "not_a_strategy"})
    assert bad.status_code == 400


def test_p2_backtest_job_returns_run_id_and_rejects_overlap(tmp_path, monkeypatch):
    from asqt.research_jobs import ResearchBusy, start_backtest_job

    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>", encoding="utf-8")
    rows, instruments = _trend_book()
    _seed(settings, rows, instruments)
    finished = start_backtest_job(ETF_MA_ROTATE, settings=settings, background=False)
    assert finished["status"] == "success"
    assert finished["progress_pct"] == 100
    assert finished["detail"]["reports"][0]["strategy_id"] == ETF_MA_ROTATE

    execute(
        """
        INSERT INTO research_run
            (run_id, strategy_id, status, inflight, progress_pct, started_at, created_at)
        VALUES ('hold-1', 'all', 'running', 1, 10, '2026-09-08T00:00:00+00:00', '2026-09-08T00:00:00+00:00')
        """,
        settings=settings,
    )
    with pytest.raises(ResearchBusy):
        start_backtest_job(STOCK_MOMENTUM_TOPK, settings=settings, background=False)

    from asqt import config as config_module

    execute("UPDATE research_run SET inflight = NULL, status = 'success' WHERE run_id = 'hold-1'", settings=settings)
    config_module.get_settings.cache_clear()
    monkeypatch.setattr("asqt.api.get_settings", lambda: settings)
    client = TestClient(create_app())
    created = client.post("/api/research/backtest", json={"strategy_id": ETF_MA_ROTATE})
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["status"] in {"queued", "running", "success"}
    row = None
    for _ in range(40):
        row = client.get(f"/api/research/backtest/{run_id}").json()
        if row["status"] not in {"queued", "running"}:
            break
        import time

        time.sleep(0.05)
    assert row["status"] == "success"
    assert row["progress_pct"] == 100
    unknown = client.post("/api/research/backtest", json={"strategy_id": "nope"})
    assert unknown.status_code == 400
