"""GATE-A1: Point-in-time helpers — strict acceptance tests."""

from __future__ import annotations

import pytest

from asqt.events import events_asof, holder_net_in_window
from asqt.factor_pipeline import series_asof
from asqt.pit import (
    PitError,
    filter_rows_on_or_before,
    in_closed_window,
    on_or_before,
    parse_asof,
    series_asof as pit_series_asof,
    undated_allowed,
)


def test_gate_a1_parse_asof_accepts_and_rejects():
    assert parse_asof("2024-03-15") == "2024-03-15"
    assert parse_asof("20240315") == "2024-03-15"
    with pytest.raises(PitError):
        parse_asof(None)
    with pytest.raises(PitError):
        parse_asof("bad")
    with pytest.raises(PitError):
        parse_asof("")


def test_gate_a1_on_or_before_inclusive_no_lookahead():
    assert on_or_before("2024-03-15", "2024-03-15") is True
    assert on_or_before("2024-03-14", "2024-03-15") is True
    assert on_or_before("2024-03-16", "2024-03-15") is False
    assert on_or_before(None, "2024-03-15") is False
    assert on_or_before("", "2024-03-15") is False


def test_gate_a1_in_closed_window():
    assert in_closed_window("2024-03-10", start="2024-03-01", end="2024-03-15")
    assert not in_closed_window("2024-02-28", start="2024-03-01", end="2024-03-15")
    assert not in_closed_window("2024-03-16", start="2024-03-01", end="2024-03-15")


def test_gate_a1_undated_backtest_drops_live_keeps_policy():
    assert undated_allowed("backtest", asof="2024-01-01") is False
    # live + historical asof far from today → not allowed
    assert undated_allowed("live", asof="2020-01-01") is False


def test_gate_a1_filter_rows_undated_modes():
    rows = [
        {"event_date": "2024-03-10", "id": 1},
        {"event_date": "2024-03-20", "id": 2},
        {"event_date": None, "id": 3},
        {"event_date": "", "id": 4},
    ]
    backtest = filter_rows_on_or_before(rows, "2024-03-15", date_key="event_date", mode="backtest")
    assert [r["id"] for r in backtest] == [1]
    forced = filter_rows_on_or_before(
        rows, "2024-03-15", date_key="event_date", mode="backtest", keep_undated=True
    )
    assert {r["id"] for r in forced} == {1, 3, 4}


def test_gate_a1_series_asof_excludes_future_bars():
    series = [
        {"trade_date": "2024-03-01", "close": 1},
        {"trade_date": "2024-03-15", "close": 2},
        {"trade_date": "2024-03-16", "close": 3},
    ]
    got = pit_series_asof(series, "2024-03-15")
    assert [r["trade_date"] for r in got] == ["2024-03-01", "2024-03-15"]
    # factor_pipeline re-exports same semantics
    assert [r["trade_date"] for r in series_asof(series, "2024-03-15")] == [
        "2024-03-01",
        "2024-03-15",
    ]


def test_gate_a1_events_asof_no_lookahead():
    rows = [
        {"event_date": "2024-03-15", "asof_date": "2024-03-15", "symbol": "000001.SZ"},
        {"event_date": "2024-03-16", "asof_date": "2024-03-16", "symbol": "000001.SZ"},
        {"event_date": "2024-03-10", "asof_date": "2024-03-20", "symbol": "000001.SZ"},  # known late
    ]
    got = events_asof(rows, "2024-03-15")
    assert len(got) == 1
    assert got[0]["event_date"] == "2024-03-15"


def test_gate_a1_holder_net_window_excludes_future():
    events = [
        {
            "symbol": "000001.SZ",
            "event_type": "holder_increase",
            "event_date": "2024-03-10",
            "value": 100,
        },
        {
            "symbol": "000001.SZ",
            "event_type": "holder_increase",
            "event_date": "2024-03-20",
            "value": 999,
        },
    ]
    assert holder_net_in_window(events, "000001.SZ", "2024-03-15", lookback_days=30) == 100.0
