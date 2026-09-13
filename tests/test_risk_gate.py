"""GATE-B1 / B2: decision ratings + risk_gate reason codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from asqt.config import Settings
from asqt.decision import (
    RATING_REVIEW,
    PortfolioRating,
    TraderAction,
    decision_from_targets,
    extract_rating,
    rating_or_review,
    rating_to_action,
    weight_to_rating,
)
from asqt.db import execute, initialize_database
from asqt.ops import set_kill_switch
from asqt.risk_gate import (
    REASON_CALENDAR_CLOSED,
    REASON_KILL_SWITCH,
    REASON_NOT_PAPER,
    REASON_OVERRIDE_CONFLICT,
    REASON_QUALITY_BLOCK,
    REASON_STALE_DATA,
    detect_override_conflicts,
    evaluate,
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


def test_gate_b1_extract_rating_and_review_sentinel():
    assert extract_rating("Rating: Overweight") == PortfolioRating.OVERWEIGHT.value
    assert extract_rating("we remain Buy on the name") == PortfolioRating.BUY.value
    assert extract_rating("no clear call") is None
    assert rating_or_review("no clear call") == RATING_REVIEW
    assert rating_or_review("") == RATING_REVIEW
    # Must NOT silently become Hold
    assert rating_or_review("ambiguous") != PortfolioRating.HOLD.value


def test_gate_b1_weight_mapping_and_action():
    assert weight_to_rating(0.2) == PortfolioRating.BUY.value
    assert weight_to_rating(0.08) == PortfolioRating.OVERWEIGHT.value
    assert weight_to_rating(0.0) == PortfolioRating.HOLD.value
    assert weight_to_rating(-0.2) == PortfolioRating.SELL.value
    assert rating_to_action(PortfolioRating.OVERWEIGHT.value) == TraderAction.BUY.value
    assert rating_to_action(RATING_REVIEW) == RATING_REVIEW
    assert rating_to_action("TotallyUnknown") == RATING_REVIEW
    summary = decision_from_targets({"000001.SZ": 0.2, "000002.SZ": 0.0})
    assert summary["rating"] == PortfolioRating.BUY.value
    assert summary["action"] == TraderAction.BUY.value
    assert summary["n"] == 2


def test_gate_b2_quality_block(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT INTO quality_issue
            (issue_id, dataset, symbol, trade_date, check_type, severity, status, diff)
        VALUES ('b2-q', 'market_daily', '000001.SZ', '2024-01-08', 'missing', 'block', 'open', 'x')
        """,
        settings=settings,
    )
    result = evaluate(purpose="orders", strategy_id="stock_momentum_topk", trade_date="2024-01-08", settings=settings)
    assert result.rejected
    assert result.reason_code == REASON_QUALITY_BLOCK


def test_gate_b2_kill_flatten_and_admit_reject(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    set_kill_switch(True, "b2", settings=settings)
    orders = evaluate(
        purpose="orders",
        strategy_id="stock_momentum_topk",
        trade_date="2024-01-08",
        settings=settings,
    )
    assert orders.approved
    assert orders.flatten_only
    assert orders.reason_code == REASON_KILL_SWITCH

    admit = evaluate(purpose="admit", strategy_id="stock_momentum_topk", settings=settings, require_experiment=False)
    assert admit.rejected
    assert admit.reason_code == REASON_KILL_SWITCH
    set_kill_switch(False, "clear", settings=settings)


def test_gate_b2_calendar_closed(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT OR REPLACE INTO trade_calendar
            (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
        VALUES ('2024-01-07', 'CN', 0, NULL, NULL, NULL, NULL)
        """,
        settings=settings,
    )
    result = evaluate(purpose="orders", trade_date="2024-01-07", settings=settings)
    assert result.rejected
    assert result.reason_code == REASON_CALENDAR_CLOSED


def test_gate_b2_not_paper_lifecycle(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT INTO strategy_version
            (strategy_id, version, status, parameter_set_id, created_at)
        VALUES ('stock_momentum_topk', 'v1', 'draft', 'p', '2024-01-01')
        """,
        settings=settings,
    )
    result = evaluate(
        purpose="orders",
        strategy_id="stock_momentum_topk",
        trade_date="2024-01-08",
        settings=settings,
    )
    assert result.rejected
    assert result.reason_code == REASON_NOT_PAPER


def test_gate_b2_override_conflict(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT INTO paper_override
            (strategy_id, symbol, action, weight, reason, actor, updated_at)
        VALUES ('stock_momentum_topk', '000001.SZ', 'force_in', 1.5, 'bad', 't', CURRENT_TIMESTAMP)
        """,
        settings=settings,
    )
    assert detect_override_conflicts("stock_momentum_topk", settings=settings) == REASON_OVERRIDE_CONFLICT
    execute(
        """
        INSERT INTO strategy_version
            (strategy_id, version, status, parameter_set_id, created_at)
        VALUES ('stock_momentum_topk', 'v1', 'paper', 'p', '2024-01-01')
        """,
        settings=settings,
    )
    result = evaluate(
        purpose="orders",
        strategy_id="stock_momentum_topk",
        trade_date="2024-01-08",
        settings=settings,
    )
    assert result.rejected
    assert result.reason_code == REASON_OVERRIDE_CONFLICT


def test_gate_b2_stale_block(tmp_path: Path, monkeypatch):
    from asqt.storage import upsert_market_daily

    monkeypatch.setenv("ASQT_STALE_MAX_SESSIONS", "1")
    monkeypatch.setenv("ASQT_STALE_SEVERITY", "block")
    settings = make_settings(tmp_path)
    initialize_database(settings)
    for d in ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]:
        execute(
            """
            INSERT OR REPLACE INTO trade_calendar
                (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
            VALUES (?, 'CN', 1, '09:30', '15:00', NULL, NULL)
            """,
            (d,),
            settings=settings,
        )
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
                "adj_factor": 1.0,
                "source": "x",
                "version": "x",
            }
        ],
        settings=settings,
    )
    result = evaluate(purpose="orders", trade_date="2024-01-08", settings=settings)
    assert result.rejected
    assert result.reason_code == REASON_STALE_DATA


def test_gate_b2_approve_path(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    execute(
        """
        INSERT INTO strategy_version
            (strategy_id, version, status, parameter_set_id, created_at)
        VALUES ('stock_momentum_topk', 'v1', 'paper', 'p', '2024-01-01')
        """,
        settings=settings,
    )
    execute(
        """
        INSERT OR REPLACE INTO trade_calendar
            (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
        VALUES ('2024-01-08', 'CN', 1, '09:30', '15:00', NULL, NULL)
        """,
        settings=settings,
    )
    result = evaluate(
        purpose="orders",
        strategy_id="stock_momentum_topk",
        trade_date="2024-01-08",
        settings=settings,
        check_overrides=False,
    )
    assert result.approved
    assert result.flatten_only is False
    assert result.reason_code == "ok"
