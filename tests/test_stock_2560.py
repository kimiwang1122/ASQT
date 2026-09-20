from __future__ import annotations

from asqt.factors import _sma, closes_asof, rule_2560
from asqt.strategies import STOCK_2560, STRATEGY_SPECS, factor_rows, weights_for
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


def _hist(*, n: int = 70, close_fn, vol_fn) -> list[dict]:
    return [
        {
            "trade_date": date,
            "close": float(close_fn(i)),
            "adj_factor": 1.0,
            "volume": float(vol_fn(i)),
        }
        for i, date in enumerate(_dates(n))
    ]


def _bar(symbol: str, trade_date: str, close: float, volume: float) -> dict:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "amount": close * volume,
        "adj_factor": 1.0,
        "source": "test",
        "version": "2560",
    }


def test_rule_2560_requires_rising_ma25_and_vol5_over_vol60():
    up = _hist(close_fn=lambda i: 10 + i * 0.1, vol_fn=lambda i: 1000)
    assert rule_2560(up) is None  # VOL5 == VOL60

    setup = _hist(close_fn=lambda i: 10 + i * 0.05, vol_fn=lambda i: 1000 if i < 65 else 8000)
    closes = closes_asof(setup)
    setup[-1]["close"] = _sma(closes, 25, end=len(closes))  # sit on MA25
    score = rule_2560(setup)
    assert score is not None
    assert score > 1.0

    dead_vol = _hist(
        close_fn=lambda i: 10 + i * 0.05,
        vol_fn=lambda i: 8000 if i < 65 else 100,
    )
    assert rule_2560(dead_vol) is None


def test_rule_2560_holds_after_breakout_exits_below_ma25():
    """Entry on pullback; next days above band still score; drop under MA25 clears."""
    hist = _hist(close_fn=lambda i: 10 + i * 0.05, vol_fn=lambda i: 1000 if i < 65 else 8000)
    closes = closes_asof(hist)
    ma25 = _sma(closes, 25, end=len(closes))
    hist[-1]["close"] = ma25  # entry: sit on MA25 with volume
    assert rule_2560(hist) is not None

    # breakout day: leave ±2% band, still rising MA25 → hold
    hist.append(
        {
            "trade_date": "2024-04-01",
            "close": ma25 * 1.08,
            "adj_factor": 1.0,
            "volume": 9000,
        }
    )
    hold = rule_2560(hist)
    assert hold is not None
    assert hold > 1.0

    # crash through MA25 → exit
    hist.append(
        {
            "trade_date": "2024-04-02",
            "close": ma25 * 0.90,
            "adj_factor": 1.0,
            "volume": 9000,
        }
    )
    assert rule_2560(hist) is None


def test_stock_2560_sticky_keeps_hold_over_new_entry():
    """Prior hold stays; new entry only fills free slots."""
    hold_sym = "000001.SZ"
    entry_sym = "000002.SZ"
    dates = _dates(100)
    rows = []
    for i, trade_date in enumerate(dates):
        close = 10 + i * 0.05
        rows.append(_bar(hold_sym, trade_date, close, 1000 if i < 95 else 9000))
        rows.append(_bar(entry_sym, trade_date, close, 1000 if i < 95 else 9000))
    hold_hist = [row for row in rows if row["symbol"] == hold_sym]
    entry_hist = [row for row in rows if row["symbol"] == entry_sym]
    parked = _sma(closes_asof(hold_hist), 25, end=len(hold_hist))
    # day -2: both enter on MA25
    hold_hist[-2]["close"] = parked
    entry_hist[-2]["close"] = parked
    # day -1: hold breaks out (hold phase); entry sits again (re-entry / entry phase)
    hold_hist[-1]["close"] = parked * 1.08
    entry_hist[-1]["close"] = parked
    asof = dates[-1]
    classic = {
        "ma_fast": 5,
        "ma_slow": 25,
        "vol_fast": 5,
        "vol_slow": 60,
        "pullback_band": 0.02,
        "top_k": 1,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    }
    sticky = weights_for(STOCK_2560, rows, asof, params=classic, held_symbols=[hold_sym])
    assert list(sticky) == [hold_sym]
    fresh = weights_for(STOCK_2560, rows, asof, params=classic, held_symbols=[])
    assert len(fresh) == 1


def test_stock_2560_weights_top_k_from_setup():
    hot = "000001.SZ"
    cold = "000002.SZ"
    dates = _dates(100)
    rows = []
    for i, trade_date in enumerate(dates):
        close = 10 + i * 0.05
        rows.append(_bar(hot, trade_date, close, 1000 if i < 95 else 9000))
        rows.append(_bar(cold, trade_date, close, 500))
    hot_hist = [row for row in rows if row["symbol"] == hot]
    parked = _sma(closes_asof(hot_hist), 25, end=len(hot_hist))
    hot_hist[-1]["close"] = parked
    asof = dates[-1]
    classic = {
        "ma_fast": 5,
        "ma_slow": 25,
        "vol_fast": 5,
        "vol_slow": 60,
        "pullback_band": 0.02,
        "top_k": 5,
        "max_weight": 0.10,
        "gross_limit": 0.95,
    }
    weights = weights_for(STOCK_2560, rows, asof, params=classic)
    assert hot in weights
    assert cold not in weights
    factors = factor_rows(STOCK_2560, rows, asof, source_run_id="t2560", params=classic)
    assert {row["symbol"] for row in factors} == {hot}
    assert STRATEGY_SPECS[STOCK_2560]["parameter_set_id"] == "stock_2560.k10.f5.s20.vf5.vs90.b30"
    assert (
        suggest_parameter_set_id(STOCK_2560, STRATEGY_SPECS[STOCK_2560]["params"])
        == "stock_2560.k10.f5.s20.vf5.vs90.b30"
    )
    assert len(DEFAULT_GRIDS[STOCK_2560]) == 12
