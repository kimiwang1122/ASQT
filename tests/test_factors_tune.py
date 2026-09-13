from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from asqt.config import Settings
from asqt.db import execute, initialize_database
from asqt.factors import (
    ma_gap,
    momentum,
    momentum_skip_month,
    reversal,
    risk_adjusted_momentum,
    volatility,
    volume_z,
)
from asqt.storage import write_market_daily
from asqt.strategies import (
    ETF_MA_ROTATE,
    STOCK_LOWVOL_MOMENTUM,
    STOCK_MOMENTUM_SKIP_MONTH,
    STOCK_MOMENTUM_TOPK,
    STOCK_MOMENTUM_VOLUME_CONFIRM,
    STRATEGY_SPECS,
    factor_rows,
    signal_etf_ma_rotate,
    signal_stock_lowvol_momentum,
    signal_stock_momentum_skip_month,
    signal_stock_momentum_topk,
    signal_stock_momentum_volume_confirm,
    weights_for,
)
from asqt.tune import DEFAULT_GRIDS, run_tune, suggest_parameter_set_id


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


def _bars():
    rows, instruments = _trend_book()
    return rows, instruments


def test_factor_helpers_basic():
    rows = [
        {"trade_date": f"2024-01-{i:02d}", "close": 10 + i, "adj_factor": 1.0, "volume": 1000 + i * 10}
        for i in range(1, 25)
    ]
    assert momentum(rows, 5) is not None
    assert ma_gap(rows, 10) is not None
    assert volatility(rows, 10) is not None
    assert reversal(rows, 5) == -momentum(rows, 5)
    assert volume_z(rows, 10) is not None
    assert risk_adjusted_momentum(rows, lookback=10, vol_window=10) is not None


def test_momentum_skip_month_basic():
    # 30 bars: closes 10..39
    rows = [
        {"trade_date": f"2024-03-{i:02d}", "close": 10.0 + i, "adj_factor": 1.0, "volume": 1000}
        for i in range(1, 31)
    ]
    # lookback=10, skip=2 → end=hist[-3]=close 38, start=hist[-11]=close 30 → 38/30-1
    score = momentum_skip_month(rows, lookback=10, skip=2)
    assert score is not None
    assert abs(score - (38.0 / 30.0 - 1.0)) < 1e-12
    assert momentum_skip_month(rows, lookback=10, skip=0) == momentum(rows, 10)
    assert momentum_skip_month(rows, lookback=40, skip=21) is None  # too short
    assert momentum_skip_month(rows, lookback=10, skip=10) is None  # lookback <= skip
    assert momentum_skip_month(rows[:5], lookback=10, skip=2) is None


def test_legacy_momentum_matches_factor_helper(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _bars()
    _seed(settings, rows, instruments)
    asof = sorted({r["trade_date"] for r in rows})[-1]
    w1 = signal_stock_momentum_topk(rows, asof)
    w2 = weights_for(STOCK_MOMENTUM_TOPK, rows, asof)
    assert w1 == w2
    w_ma = signal_etf_ma_rotate(rows, asof)
    assert isinstance(w_ma, dict)


def test_new_strategies_emit_weights_and_factors(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _bars()
    _seed(settings, rows, instruments)
    asof = sorted({r["trade_date"] for r in rows})[-5]
    low = signal_stock_lowvol_momentum(rows, asof)
    assert isinstance(low, dict)
    filt = weights_for("etf_ma_momentum_filter", rows, asof)
    assert isinstance(filt, dict)
    factors = factor_rows(STOCK_LOWVOL_MOMENTUM, rows, asof, source_run_id="t")
    names = {row["factor_name"] for row in factors}
    assert "stock_mom_over_vol" in names or not factors  # empty ok if series short
    assert STOCK_LOWVOL_MOMENTUM in STRATEGY_SPECS
    assert STRATEGY_SPECS[STOCK_LOWVOL_MOMENTUM]["parameter_set_id"] != STRATEGY_SPECS[STOCK_MOMENTUM_TOPK][
        "parameter_set_id"
    ]


def test_tune_grid_writes_report(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _bars()
    _seed(settings, rows, instruments)
    # Tiny grid for speed.
    grid = [
        {"lookback": 10, "vol_window": 10, "top_k": 3, "max_weight": 0.10, "gross_limit": 0.95},
        {"lookback": 20, "vol_window": 10, "top_k": 3, "max_weight": 0.10, "gross_limit": 0.95},
    ]
    report = run_tune(STOCK_LOWVOL_MOMENTUM, grid=grid, settings=settings)
    assert report["ok"] is True
    assert report["grid_size"] == 2
    assert report["winner"]["suggested_parameter_set_id"].startswith("stock_lowvol_momentum.")
    assert "experiment_path" in report
    assert report["winner"]["metrics"]["is"]["n_days"] >= 1


def test_suggest_parameter_set_id_stable():
    assert (
        suggest_parameter_set_id(
            STOCK_LOWVOL_MOMENTUM,
            {"lookback": 20, "vol_window": 20, "top_k": 5, "max_weight": 0.1, "gross_limit": 0.95},
        )
        == "stock_lowvol_momentum.k5.l20.v20"
    )
    assert (
        suggest_parameter_set_id(
            ETF_MA_ROTATE,
            {"window": 20, "max_weight": 0.2, "gross_limit": 0.95},
        )
        == "etf_ma_rotate.w20"
    )
    assert (
        suggest_parameter_set_id(
            "stock_short_reversal_topk",
            {"lookback": 10, "top_k": 2, "max_weight": 0.1, "gross_limit": 0.95},
        )
        == "stock_short_reversal_topk.k2.l10"
    )
    assert (
        suggest_parameter_set_id(
            "stock_short_reversal_topk",
            {
                "lookback": 5,
                "top_k": 5,
                "max_weight": 0.1,
                "gross_limit": 0.70,
                "rebalance_every_n": 5,
            },
        )
        == "stock_short_reversal_topk.k5.l5.g70.r5"
    )
    assert (
        suggest_parameter_set_id(
            STOCK_MOMENTUM_VOLUME_CONFIRM,
            {
                "lookback": 40,
                "vol_z_window": 20,
                "min_volume_z": 0.0,
                "top_k": 5,
                "max_weight": 0.1,
                "gross_limit": 0.95,
            },
        )
        == "stock_momentum_volume_confirm.k5.l40.vz20"
    )
    assert (
        suggest_parameter_set_id(
            STOCK_MOMENTUM_SKIP_MONTH,
            {"lookback": 252, "skip": 21, "top_k": 5, "max_weight": 0.1, "gross_limit": 0.95},
        )
        == "stock_momentum_skip_month.k5.l252.s21"
    )


def test_stock_short_reversal_topk_weights_and_factors(tmp_path):
    from asqt.strategies import STOCK_SHORT_REVERSAL_TOPK, signal_stock_short_reversal_topk

    settings = make_settings(tmp_path)
    rows, instruments = _bars()
    _seed(settings, rows, instruments)
    asof = sorted({r["trade_date"] for r in rows})[-5]
    weights = signal_stock_short_reversal_topk(rows, asof)
    assert isinstance(weights, dict)
    assert weights_for(STOCK_SHORT_REVERSAL_TOPK, rows, asof) == weights
    factors = factor_rows(STOCK_SHORT_REVERSAL_TOPK, rows, asof, source_run_id="rev")
    assert all(row["factor_name"] == "stock_reversal" for row in factors)
    assert STRATEGY_SPECS[STOCK_SHORT_REVERSAL_TOPK]["parameter_set_id"] == "stock_short_reversal_topk.k2.l10"
    assert STRATEGY_SPECS[STOCK_SHORT_REVERSAL_TOPK]["params"]["lookback"] == 10
    assert STRATEGY_SPECS[STOCK_SHORT_REVERSAL_TOPK]["params"]["top_k"] == 2


def test_stock_momentum_volume_confirm_weights_and_factors(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _bars()
    _seed(settings, rows, instruments)
    asof = sorted({r["trade_date"] for r in rows})[-5]
    weights = signal_stock_momentum_volume_confirm(rows, asof)
    assert isinstance(weights, dict)
    assert weights_for(STOCK_MOMENTUM_VOLUME_CONFIRM, rows, asof) == weights
    factors = factor_rows(STOCK_MOMENTUM_VOLUME_CONFIRM, rows, asof, source_run_id="vz")
    names = {row["factor_name"] for row in factors}
    assert names <= {"stock_momentum", "stock_volume_z"}
    assert names & {"stock_momentum", "stock_volume_z"} or not factors
    assert (
        STRATEGY_SPECS[STOCK_MOMENTUM_VOLUME_CONFIRM]["parameter_set_id"]
        == "stock_momentum_volume_confirm.k5.l40.vz20"
    )
    assert len(DEFAULT_GRIDS[STOCK_MOMENTUM_VOLUME_CONFIRM]) <= 24


def test_stock_momentum_skip_month_weights_and_factors(tmp_path):
    settings = make_settings(tmp_path)
    rows, instruments = _bars()
    _seed(settings, rows, instruments)
    asof = sorted({r["trade_date"] for r in rows})[-5]
    # Fixture is short vs lookback=252; smoke with shorter params.
    weights = signal_stock_momentum_skip_month(
        rows, asof, params={"lookback": 40, "skip": 5, "top_k": 3}
    )
    assert isinstance(weights, dict)
    assert weights_for(
        STOCK_MOMENTUM_SKIP_MONTH, rows, asof, params={"lookback": 40, "skip": 5, "top_k": 3}
    ) == weights
    factors = factor_rows(
        STOCK_MOMENTUM_SKIP_MONTH,
        rows,
        asof,
        source_run_id="skip",
        params={"lookback": 40, "skip": 5, "top_k": 3},
    )
    assert all(row["factor_name"] == "stock_momentum_skip_month" for row in factors)
    assert factors  # 60-day book is enough for l40/s5
    assert (
        STRATEGY_SPECS[STOCK_MOMENTUM_SKIP_MONTH]["parameter_set_id"]
        == "stock_momentum_skip_month.k5.l252.s21"
    )
    assert len(DEFAULT_GRIDS[STOCK_MOMENTUM_SKIP_MONTH]) <= 24


def test_precompute_select_targets_matches_weights_for():
    from asqt.factor_pipeline import build_data_frame, compute_factor_frame
    from asqt.selectors import select_targets
    from asqt.strategies import (
        ETF_MA_MOMENTUM_FILTER,
        ETF_MOMENTUM_TOPK,
        STOCK_LOWVOL_MOMENTUM,
        STOCK_SHORT_REVERSAL_TOPK,
        factor_specs_for,
        selector_rules_for,
    )

    rows, _instruments = _bars()
    asof = sorted({r["trade_date"] for r in rows})[-5]
    grouped = build_data_frame(rows)
    limits = [{"symbol": "000002.SZ", "trade_date": asof, "is_suspended": 1}]
    for strategy_id in (
        STOCK_MOMENTUM_TOPK,
        ETF_MA_ROTATE,
        ETF_MOMENTUM_TOPK,
        STOCK_LOWVOL_MOMENTUM,
        ETF_MA_MOMENTUM_FILTER,
        STOCK_SHORT_REVERSAL_TOPK,
        STOCK_MOMENTUM_VOLUME_CONFIRM,
    ):
        factors = compute_factor_frame(
            grouped,
            factor_specs_for(strategy_id),
            asof=asof,
        )
        via_sel = select_targets(
            factors,
            asof,
            selector_rules_for(strategy_id),
            limits=limits,
        )
        via_w = weights_for(strategy_id, rows, asof, limits=limits)
        assert via_sel == via_w, strategy_id


def test_precompute_multi_day_matches_per_day_weights():
    from asqt.factor_pipeline import build_data_frame, compute_factor_frame
    from asqt.selectors import select_targets
    from asqt.strategies import factor_specs_for, selector_rules_for

    rows, _instruments = _bars()
    dates = sorted({r["trade_date"] for r in rows})
    sample = dates[-10:-1]
    grouped = build_data_frame(rows)
    strategy_id = STOCK_MOMENTUM_TOPK
    precomputed = compute_factor_frame(
        grouped,
        factor_specs_for(strategy_id),
        dates=sample,
    )
    by_date: dict[str, list] = {}
    for row in precomputed:
        by_date.setdefault(row["trade_date"], []).append(row)
    rules = selector_rules_for(strategy_id)
    for asof in sample:
        pre = select_targets(by_date.get(asof, []), asof, rules)
        live = weights_for(strategy_id, rows, asof)
        assert pre == live, asof


def test_params_hash_keeps_window_variants(tmp_path):
    from asqt.factor_pipeline import params_hash, write_factor_signals
    from asqt.db import query_all

    settings = make_settings(tmp_path)
    initialize_database(settings)
    h10 = params_hash({"lookback": 10})
    h40 = params_hash({"lookback": 40})
    assert h10 != h40
    write_factor_signals(
        [
            {
                "trade_date": "2024-06-01",
                "symbol": "000001.SZ",
                "factor_name": "stock_momentum",
                "value": 0.1,
                "model_version": "t",
                "source_run_id": "a",
                "params_hash": h10,
            },
            {
                "trade_date": "2024-06-01",
                "symbol": "000001.SZ",
                "factor_name": "stock_momentum",
                "value": 0.2,
                "model_version": "t",
                "source_run_id": "b",
                "params_hash": h40,
            },
        ],
        settings=settings,
    )
    rows = query_all(
        "SELECT value, params_hash FROM factor_signal WHERE symbol = ? ORDER BY params_hash",
        ("000001.SZ",),
        settings=settings,
    )
    assert len(rows) == 2
    assert {row["value"] for row in rows} == {0.1, 0.2}
