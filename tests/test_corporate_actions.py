from __future__ import annotations

from asqt.corporate_actions import action_explains_jump, load_corporate_actions, theoretical_ex_price
from asqt.quality import ContractQualityChecker


def _daily(symbol: str, trade_date: str, close: float, adj: float) -> dict:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1,
        "amount": close,
        "adj_factor": adj,
        "source": "test",
        "version": "test",
    }


def test_theoretical_ex_price_matches_announcements():
    byd = theoretical_ex_price(337.0, 3.974, 3.0)
    catl = theoretical_ex_price(385.9, 2.52, 1.8)
    assert byd is not None and abs(byd - 111.0087) < 0.01
    assert catl is not None and abs(catl - 212.9889) < 0.01


def test_verified_byd_and_catl_events_explain_repo_jumps():
    actions = load_corporate_actions()
    byd_prev = _daily("002594.SZ", "2025-07-28", 337.0, 1.037805)
    byd_curr = _daily("002594.SZ", "2025-07-29", 111.42, 3.150529)
    catl_prev = _daily("300750.SZ", "2023-04-25", 385.9, 1.005407)
    catl_curr = _daily("300750.SZ", "2023-04-26", 224.5, 1.821618)
    assert action_explains_jump(byd_prev, byd_curr, next(item for item in actions if item["symbol"] == "002594.SZ"))
    assert action_explains_jump(catl_prev, catl_curr, next(item for item in actions if item["symbol"] == "300750.SZ"))
    result = ContractQualityChecker().check(
        "market_daily",
        records=[byd_prev, byd_curr, catl_prev, catl_curr],
        corporate_actions=actions,
    )
    assert result["trade_allowed"] is True
    assert result["issues"] == []


def test_event_does_not_explain_inconsistent_bars():
    actions = load_corporate_actions()
    byd_action = next(item for item in actions if item["symbol"] == "002594.SZ")
    prev = _daily("002594.SZ", "2025-07-28", 337.0, 1.037805)
    # Same close after a 3x factor jump is not an ex-right print.
    bad = _daily("002594.SZ", "2025-07-29", 337.0, 3.150529)
    assert action_explains_jump(prev, bad, byd_action) is False
    blocked = ContractQualityChecker().check(
        "market_daily",
        records=[prev, bad],
        corporate_actions=actions,
    )
    assert any(item["check_type"] == "adj_conflict" and item["severity"] == "block" for item in blocked["issues"])


def test_ratio_only_without_event_still_blocks():
    result = ContractQualityChecker().check(
        "market_daily",
        records=[
            _daily("000001.SZ", "2024-01-02", 30.0, 1.0),
            _daily("000001.SZ", "2024-01-03", 10.0, 3.0),
        ],
        corporate_actions=[],
    )
    assert any(item["check_type"] == "adj_conflict" for item in result["issues"])
