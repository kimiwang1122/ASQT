"""Lab: paper param rewrite + insight attribution."""

from pathlib import Path

from asqt.db import initialize_database
from asqt.lab_insight import build_insight, calendar_buckets, label_regimes
from asqt.strategies import ETF_MA_MOMENTUM_FILTER, STRATEGY_SPECS, pin_strategy_params
from asqt.tune import suggest_parameter_set_id
from tests.test_p1_data import make_settings


def test_suggest_id_ma_filter_grid():
    params = {"ma_window": 20, "mom_lookback": 20, "top_k": 5, "max_weight": 0.2, "gross_limit": 0.95}
    assert suggest_parameter_set_id(ETF_MA_MOMENTUM_FILTER, params) == "etf_ma_momentum_filter.k5.m20.l20"


def test_pin_strategy_params_lab(tmp_path: Path):
    settings = make_settings(tmp_path)
    initialize_database(settings)
    pin = pin_strategy_params(
        ETF_MA_MOMENTUM_FILTER,
        {"ma_window": 10, "mom_lookback": 10, "top_k": 4, "max_weight": 0.2, "gross_limit": 0.95},
        settings=settings,
        persist=True,
    )
    assert pin["parameter_set_id"] == "etf_ma_momentum_filter.k4.m10.l10"
    assert STRATEGY_SPECS[ETF_MA_MOMENTUM_FILTER]["params"]["top_k"] == 4
    # restore package default so other tests stay stable
    pin_strategy_params(
        ETF_MA_MOMENTUM_FILTER,
        {"ma_window": 40, "mom_lookback": 40, "top_k": 3, "max_weight": 0.2, "gross_limit": 0.95},
        parameter_set_id="etf_ma_momentum_filter.k3.m40.l40",
        settings=settings,
        persist=True,
    )
    assert STRATEGY_SPECS[ETF_MA_MOMENTUM_FILTER]["parameter_set_id"] == "etf_ma_momentum_filter.k3.m40.l40"


def test_lab_insight_calendar_and_regimes():
    dates = [f"2024-03-{d:02d}" for d in range(1, 32)]
    closes = [100 + i for i in range(31)]
    regimes = label_regimes(dates, closes)
    assert len(regimes) == 31
    assert set(regimes) <= {"trend_up", "range", "trend_down"}
    timeline = [
        {"trade_date": dates[i], "daily_return": 0.01, "total_asset": 1_000_000 * (1 + 0.01 * i)}
        for i in range(31)
    ]
    cal = calendar_buckets(timeline)
    assert cal["weekday"]
    assert cal["month"]
    market = [
        {"symbol": "510300.SH", "trade_date": dates[i], "close": closes[i], "adj_factor": 1.0}
        for i in range(31)
    ]
    insight = build_insight(timeline, market)
    assert "calendar" in insight and "regimes" in insight
    assert insight["regimes"]["stats"]


def test_load_latest_lab_grid_from_pointer(tmp_path: Path):
    from asqt.lab_timeline import load_latest_lab_grid, write_lab_grid_latest

    settings = make_settings(tmp_path)
    summary = {
        "batch_id": "testbatch",
        "days": 240,
        "rows": [
            {
                "parameter_set_id": "etf_ma_momentum_filter.k3.m20.l20",
                "ma_window": 20,
                "top_k": 3,
                "total_return": 0.05,
                "max_drawdown": -0.09,
                "fees": 1.0,
                "regime_stats": {
                    "trend_up": {"total_return": 0.01},
                    "range": {"total_return": 0.02},
                    "trend_down": {"total_return": 0.02},
                },
            },
            {
                "parameter_set_id": "etf_ma_momentum_filter.k3.m10.l10",
                "ma_window": 10,
                "top_k": 3,
                "total_return": -0.07,
                "max_drawdown": -0.1,
                "fees": 2.0,
                "regime_stats": {},
            },
        ],
    }
    write_lab_grid_latest(summary, settings=settings)
    payload = load_latest_lab_grid(settings=settings)
    assert payload["ok"]
    assert payload["winner"]["parameter_set_id"] == "etf_ma_momentum_filter.k3.m20.l20"
    assert payload["rows"][0]["regime_return_up"] == 0.01


def test_lab_params_solo_override_multi_blocked(tmp_path: Path):
    from asqt.lab_params import apply_run_pins, resolve_run_pins, set_lab_default
    from asqt.strategies import ETF_MA_MOMENTUM_FILTER, STRATEGY_SPECS

    settings = make_settings(tmp_path)
    initialize_database(settings)
    set_lab_default(
        ETF_MA_MOMENTUM_FILTER,
        {"ma_window": 20, "mom_lookback": 20, "top_k": 3, "max_weight": 0.2, "gross_limit": 0.95},
        settings=settings,
    )
    solo = resolve_run_pins(
        [ETF_MA_MOMENTUM_FILTER],
        mode="sequential",
        lab_params={"ma_window": 10, "top_k": 5},
        settings=settings,
    )
    assert solo["mode"] == "lab_override"
    assert solo["pins"][ETF_MA_MOMENTUM_FILTER]["parameter_set_id"] == "etf_ma_momentum_filter.k5.m10.l10"
    try:
        resolve_run_pins(
            [ETF_MA_MOMENTUM_FILTER, "etf_ma_rotate"],
            mode="sequential",
            lab_params={"ma_window": 10},
            settings=settings,
        )
        raise AssertionError("expected multi lab reject")
    except ValueError as exc:
        assert "单策略" in str(exc)
    try:
        resolve_run_pins(
            [ETF_MA_MOMENTUM_FILTER],
            mode="parallel",
            lab_params={"ma_window": 10},
            settings=settings,
        )
        raise AssertionError("expected parallel lab reject")
    except ValueError as exc:
        assert "单策略" in str(exc)
    multi = apply_run_pins(
        [ETF_MA_MOMENTUM_FILTER, "etf_ma_rotate"],
        mode="parallel",
        settings=settings,
    )
    assert multi["mode"] == "defaults"
    assert STRATEGY_SPECS[ETF_MA_MOMENTUM_FILTER]["parameter_set_id"] == "etf_ma_momentum_filter.k3.m20.l20"
    # restore code default for other tests in-process
    from asqt.strategies import pin_strategy_params

    pin_strategy_params(
        ETF_MA_MOMENTUM_FILTER,
        {"ma_window": 40, "mom_lookback": 40, "top_k": 3, "max_weight": 0.2, "gross_limit": 0.95},
        parameter_set_id="etf_ma_momentum_filter.k3.m40.l40",
        settings=settings,
        persist=True,
    )
    pin_strategy_params(
        "etf_ma_rotate",
        dict(STRATEGY_SPECS["etf_ma_rotate"]["params"]),
        parameter_set_id=STRATEGY_SPECS["etf_ma_rotate"]["parameter_set_id"],
        settings=settings,
        persist=True,
    )


def test_lab_preset_crud(tmp_path: Path):
    from asqt.lab_params import delete_preset, presets_for, upsert_preset

    settings = make_settings(tmp_path)
    initialize_database(settings)
    created = upsert_preset("etf_ma_rotate", {"window": 15}, settings=settings)
    assert created["parameter_set_id"] == "etf_ma_rotate.w15"
    assert created["editable"] is True
    ids = {row["parameter_set_id"]: row for row in presets_for("etf_ma_rotate", settings=settings)}
    assert "etf_ma_rotate.w15" in ids
    assert ids["etf_ma_rotate.w15"]["source"] == "custom"
    updated = upsert_preset(
        "etf_ma_rotate",
        {"window": 25},
        replace_id="etf_ma_rotate.w15",
        settings=settings,
    )
    assert updated["parameter_set_id"] == "etf_ma_rotate.w25"
    ids = {row["parameter_set_id"] for row in presets_for("etf_ma_rotate", settings=settings)}
    assert "etf_ma_rotate.w15" not in ids
    assert "etf_ma_rotate.w25" in ids
    delete_preset("etf_ma_rotate", "etf_ma_rotate.w25", settings=settings)
    ids = {row["parameter_set_id"] for row in presets_for("etf_ma_rotate", settings=settings)}
    assert "etf_ma_rotate.w25" not in ids
    builtin = next(row["parameter_set_id"] for row in presets_for("etf_ma_rotate", settings=settings))
    try:
        delete_preset("etf_ma_rotate", builtin, settings=settings)
        raise AssertionError("expected builtin delete reject")
    except ValueError as exc:
        assert "内置" in str(exc)
