"""GATE-A2: stale_asof / NoMarketData / paper block on stale fills."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from asqt.config import Settings
from asqt.data_errors import NoMarketDataError, StaleDataError
from asqt.db import execute, initialize_database
from asqt.quality import ContractQualityChecker
from asqt.stale import (
    evaluate_market_staleness,
    latest_bar_dates,
    trading_session_lag,
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


def _cal(*dates: str) -> list[dict]:
    return [{"trade_date": d, "market": "CN", "is_open": 1} for d in dates]


def _bar(symbol: str, day: str) -> dict:
    return {
        "symbol": symbol,
        "trade_date": day,
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


def test_gate_a2_errors_are_structured():
    err = StaleDataError(
        "stale",
        asof="2024-01-10",
        latest="2024-01-02",
        lag_sessions=6,
        max_lag=5,
        symbol="000001.SZ",
    )
    assert err.code == "stale_data"
    assert err.as_dict()["lag_sessions"] == 6
    assert NoMarketDataError("empty").code == "no_market_data"


def test_gate_a2_trading_session_lag_counts_open_days_only():
    opens = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
    # weekend gap: Jan 5 → Jan 8 is one session step in the list; lag from 01-02 to 01-09
    assert trading_session_lag("2024-01-02", "2024-01-02", opens) == 0
    assert trading_session_lag("2024-01-02", "2024-01-05", opens) == 3  # 03,04,05
    assert trading_session_lag("2024-01-05", "2024-01-09", opens) == 2  # 08,09


def test_gate_a2_evaluate_stale_warn_vs_block(monkeypatch):
    opens = _cal("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09")
    records = [_bar("000001.SZ", "2024-01-02")]
    monkeypatch.setenv("ASQT_STALE_MAX_SESSIONS", "2")
    monkeypatch.setenv("ASQT_STALE_SEVERITY", "warn")
    warn = evaluate_market_staleness(
        records=records,
        calendar=opens,
        asof="2024-01-09",
        expected_symbols=["000001.SZ"],
    )
    assert warn.has_stale
    assert warn.blocked is False
    assert warn.issues[0]["check_type"] == "stale_asof"
    assert warn.issues[0]["severity"] == "warn"

    monkeypatch.setenv("ASQT_STALE_SEVERITY", "block")
    blocked = evaluate_market_staleness(
        records=records,
        calendar=opens,
        asof="2024-01-09",
        expected_symbols=["000001.SZ"],
    )
    assert blocked.blocked is True
    assert blocked.issues[0]["severity"] == "block"


def test_gate_a2_quality_checker_emits_stale_asof(monkeypatch):
    monkeypatch.setenv("ASQT_STALE_MAX_SESSIONS", "1")
    monkeypatch.setenv("ASQT_STALE_SEVERITY", "block")
    calendar = _cal("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")
    records = [_bar("000001.SZ", "2024-01-02")]
    result = ContractQualityChecker().check(
        "market_daily",
        asof="2024-01-05",
        records=records,
        calendar=calendar,
        expected_symbols=["000001.SZ"],
    )
    assert result["trade_allowed"] is False
    assert any(i["check_type"] == "stale_asof" and i["severity"] == "block" for i in result["issues"])


def test_gate_a2_fresh_data_no_stale_issue(monkeypatch):
    monkeypatch.setenv("ASQT_STALE_MAX_SESSIONS", "5")
    monkeypatch.setenv("ASQT_STALE_SEVERITY", "block")
    calendar = _cal("2024-01-02", "2024-01-03", "2024-01-04")
    records = [
        _bar("000001.SZ", "2024-01-02"),
        _bar("000001.SZ", "2024-01-03"),
        _bar("000001.SZ", "2024-01-04"),
    ]
    result = ContractQualityChecker().check(
        "market_daily",
        asof="2024-01-04",
        records=records,
        calendar=calendar,
        expected_symbols=["000001.SZ"],
    )
    assert not any(i["check_type"] == "stale_asof" for i in result["issues"])
    assert latest_bar_dates(records, "2024-01-04")["000001.SZ"] == "2024-01-04"


def test_gate_a2_paper_rejects_when_stale_block(tmp_path: Path, monkeypatch):
    from asqt.paper import PaperOrderService
    from asqt.storage import upsert_market_daily
    from asqt.strategies import STOCK_MOMENTUM_TOPK

    monkeypatch.setenv("ASQT_STALE_MAX_SESSIONS", "1")
    monkeypatch.setenv("ASQT_STALE_SEVERITY", "block")
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
    initialize_database(settings)

    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
    for d in days:
        execute(
            """
            INSERT OR REPLACE INTO trade_calendar
                (trade_date, market, is_open, open_time, close_time, prev_trade_date, next_trade_date)
            VALUES (?, 'CN', 1, '09:30', '15:00', NULL, NULL)
            """,
            (d,),
            settings=settings,
        )
    # Bars only through 01-02; fill date 01-08 is far stale.
    upsert_market_daily([_bar("000001.SZ", "2024-01-02")], settings=settings)

    svc = PaperOrderService(settings)
    out = svc.build_orders(
        "2024-01-08",
        STOCK_MOMENTUM_TOPK,
        signal_date="2024-01-05",
        apply_fills=False,
    )
    assert out
    assert out[0]["status"] == "rejected"
    assert out[0]["risk_tags"] == "stale_data"


def test_gate_a2_paper_allows_when_severity_warn(tmp_path: Path, monkeypatch):
    from asqt.paper import PaperOrderService
    from asqt.storage import upsert_market_daily
    from asqt.strategies import STOCK_MOMENTUM_TOPK

    monkeypatch.setenv("ASQT_STALE_MAX_SESSIONS", "1")
    monkeypatch.setenv("ASQT_STALE_SEVERITY", "warn")
    settings = make_settings(tmp_path)
    (tmp_path / "frontend").mkdir(parents=True, exist_ok=True)
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
    upsert_market_daily([_bar("000001.SZ", "2024-01-02")], settings=settings)
    svc = PaperOrderService(settings)
    out = svc.build_orders(
        "2024-01-08",
        STOCK_MOMENTUM_TOPK,
        signal_date="2024-01-05",
        apply_fills=False,
    )
    # warn mode: must NOT reject solely for stale_data (may reject for not_paper later)
    assert not (out and out[0].get("risk_tags") == "stale_data")
