from __future__ import annotations

from asqt.factors import ma_gap, momentum, reversal, risk_adjusted_momentum, volatility, volume_z
from asqt.strategies import (
    ETF_MA_ROTATE,
    STOCK_LOWVOL_MOMENTUM,
    STOCK_MOMENTUM_TOPK,
    STRATEGY_SPECS,
    factor_rows,
    signal_etf_ma_rotate,
    signal_stock_lowvol_momentum,
    signal_stock_momentum_topk,
    weights_for,
)
from asqt.tune import run_tune, simulate_path, suggest_parameter_set_id
from tests.test_p2_research import _seed, _trend_book, make_settings


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
