"""GATE-D3: selectors filter_expr AND/OR DSL (self-built)."""

from __future__ import annotations

import pytest

from asqt.selectors import eval_filter_expr, select_targets


def _rows(asof: str = "2024-01-10") -> list[dict]:
    return [
        {"trade_date": asof, "symbol": "AAA", "factor_name": "mom", "value": 0.2},
        {"trade_date": asof, "symbol": "AAA", "factor_name": "vol", "value": 0.1},
        {"trade_date": asof, "symbol": "BBB", "factor_name": "mom", "value": 0.05},
        {"trade_date": asof, "symbol": "BBB", "factor_name": "vol", "value": 0.4},
        {"trade_date": asof, "symbol": "CCC", "factor_name": "mom", "value": 0.3},
        {"trade_date": asof, "symbol": "CCC", "factor_name": "vol", "value": 0.05},
        {"trade_date": asof, "symbol": "DDD", "factor_name": "mom", "value": -0.1},
        {"trade_date": asof, "symbol": "DDD", "factor_name": "vol", "value": 0.02},
    ]


def test_gate_d3_legacy_filters_remain_and():
    weights = select_targets(
        _rows(),
        "2024-01-10",
        {
            "filters": [{"factor": "mom", "op": ">", "value": 0.1}, {"factor": "vol", "op": "<", "value": 0.2}],
            "score_factor": None,
            "top_k": None,
            "max_weight": 1.0,
            "gross_limit": 1.0,
        },
    )
    assert set(weights) == {"AAA", "CCC"}


def test_gate_d3_any_or_and_nested():
    assert eval_filter_expr({"mom": 0.2, "vol": 0.5}, {"any": [{"factor": "mom", "op": ">", "value": 0.5}, {"factor": "vol", "op": ">", "value": 0.4}]})
    assert not eval_filter_expr({"mom": 0.1, "vol": 0.1}, {"any": [{"factor": "mom", "op": ">", "value": 0.5}]})

    weights = select_targets(
        _rows(),
        "2024-01-10",
        {
            "filter_expr": {
                "any": [
                    {"all": [{"factor": "mom", "op": ">", "value": 0.15}, {"factor": "vol", "op": "<", "value": 0.15}]},
                    {"factor": "vol", "op": ">", "value": 0.35},
                ]
            },
            "score_factor": "mom",
            "top_k": 10,
            "max_weight": 0.5,
            "gross_limit": 1.0,
            "ascending": False,
        },
    )
    # AAA (mom+vol), CCC (mom+vol), BBB (vol>0.35); DDD fails
    assert set(weights) == {"AAA", "BBB", "CCC"}
    assert weights["AAA"] == pytest.approx(weights["BBB"])


def test_gate_d3_filter_expr_overrides_flat_filters():
    weights = select_targets(
        _rows(),
        "2024-01-10",
        {
            "filters": [{"factor": "mom", "op": ">", "value": 0.99}],  # would select none
            "filter_expr": {"any": [{"factor": "mom", "op": ">", "value": 0.25}]},
            "score_factor": None,
            "top_k": None,
            "max_weight": 1.0,
            "gross_limit": 1.0,
        },
    )
    assert set(weights) == {"CCC"}
