from __future__ import annotations

from asqt.factors import rule_yin_arb
from asqt.strategies import STOCK_YIN_ARB, STRATEGY_SPECS, factor_rows, weights_for
from asqt.tune import DEFAULT_GRIDS, suggest_parameter_set_id


def _dates(n: int) -> list[str]:
    dates = []
    day = 1
    month = 1
    for _ in range(n):
        dates.append(f"2024-{month:02d}-{day:02d}")
        day += 1
        if day > 28:
            day = 1
            month += 1
    return dates


def _setup(*, burst: bool = True, yin: bool = True, above_prev: bool = True, near_ma: bool = True) -> list[dict]:
    n = 40
    rows = []
    for i, date in enumerate(_dates(n)):
        close = 10.0 + 0.02 * i
        open_px = close
        volume = 1000.0
        if i == n - 3:
            volume = 2000.0 if burst else 1000.0
        if i == n - 1:
            volume = 800.0
            if yin:
                open_px = close / 0.99
            if not above_prev:
                close = close - 0.05
                open_px = close / 0.99 if yin else close
            if not near_ma:
                close = close * 1.05
                open_px = close / 0.99 if yin else close
        rows.append(
            {
                "symbol": "000001.SZ",
                "trade_date": date,
                "open": open_px,
                "high": max(open_px, close),
                "low": min(open_px, close),
                "close": close,
                "volume": volume,
                "amount": close * volume,
                "adj_factor": 1.0,
                "source": "test",
                "version": "yin",
            }
        )
    return rows


def test_rule_yin_arb_requires_burst_yin_and_ma_pullback():
    assert rule_yin_arb(_setup()) is not None
    assert rule_yin_arb(_setup(burst=False)) is None
    assert rule_yin_arb(_setup(yin=False)) is None
    assert rule_yin_arb(_setup(above_prev=False)) is None
    assert rule_yin_arb(_setup(near_ma=False)) is None


def test_yin_arb_timeline_matches_prefix_scores():
    from asqt.factors import rule_yin_arb_timeline

    rows = _setup()
    timeline = rule_yin_arb_timeline(rows)
    assert timeline[-1] == rule_yin_arb(rows)
    for i in range(22, len(rows)):
        assert timeline[i] == rule_yin_arb(rows[: i + 1])


def test_yin_arb_weights_and_pin():
    rows = _setup()
    asof = rows[-1]["trade_date"]
    params = dict(STRATEGY_SPECS[STOCK_YIN_ARB]["params"])
    weights = weights_for(STOCK_YIN_ARB, rows, asof, params=params)
    assert weights == {"000001.SZ": 0.10}
    factors = factor_rows(STOCK_YIN_ARB, rows, asof, source_run_id="tyin", params=params)
    assert any(row["factor_name"] == "stock_yin_arb" and row["value"] > 0 for row in factors)
    pin = STRATEGY_SPECS[STOCK_YIN_ARB]["parameter_set_id"]
    assert pin == "stock_yin_arb.k10.f10.s20.bl5.br180.b25.mg30"
    assert suggest_parameter_set_id(STOCK_YIN_ARB, params) == pin
    assert len(DEFAULT_GRIDS[STOCK_YIN_ARB]) == 8
    sl_params = {**params, "stop_loss": 0.04, "take_profit": 0.20}
    assert suggest_parameter_set_id(STOCK_YIN_ARB, sl_params).endswith(".sl4.tp20")
    from asqt.tune import stock_yin_arb_short_id

    assert stock_yin_arb_short_id(sl_params) == "k10.br180.b25.bl5.sl4.tp20"


def test_yin_arb_paper_top_presets_registered():
    from asqt.lab_params import builtin_presets
    from asqt.tune import stock_yin_arb_short_id

    shorts = {stock_yin_arb_short_id(row["params"]) for row in builtin_presets(STOCK_YIN_ARB)}
    assert shorts >= {
        "k10.br150.b30.bl5",
        "k10.br150.b25.bl5",
        "k10.br180.b25.bl5",
        "k5.br150.b30.bl5",
        "k5.br150.b25.bl5",
        "k5.br180.b25.bl5",
        "k10.br150.b20.bl5",
        "k10.br180.b30.bl5",
        "k5.br180.b30.bl5",
        "k5.br150.b30.bl3",
    }
