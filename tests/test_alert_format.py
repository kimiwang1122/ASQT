from __future__ import annotations

import json

from asqt.alert_format import (
    build_drawdown_payload,
    encode_alert_detail,
    format_alert_full,
    format_alert_summary,
    format_feishu_text,
)
from asqt.ops import maybe_drawdown_halt
from tests.test_p3_paper import _prepare


def test_drawdown_payload_and_templates():
    payload = build_drawdown_payload(
        dd=-0.1206,
        peak=117_094.25,
        total_asset=102_980.11,
        cash=12_345.67,
        market_value=90_634.44,
        initial_cash=100_000,
        account_id="paper:etf_momentum_topk",
        strategy_id="etf_momentum_topk",
        trade_date="2024-06-18",
        kind="stop",
    )
    row = {
        "level": "critical",
        "category": "drawdown",
        "title": "max drawdown stop",
        "detail": encode_alert_detail(payload),
    }
    summary = format_alert_summary(row)
    full = format_alert_full(row)
    feishu = format_feishu_text(row)
    assert summary == "回撤 12.06% 触发急停"
    assert "账户峰值：117,094.25" in full
    assert "当前总资产：102,980.11" in full
    assert "现金：12,345.67" in full
    assert "持仓市值：90,634.44" in full
    assert "较峰值盈亏：-14,114.14" in full
    assert "【ASQT告警】严重 · 回撤" in feishu
    assert "回撤触发急停" in feishu
    assert full in feishu


def test_maybe_drawdown_halt_persists_json_detail(tmp_path):
    settings, _engine, _service = _prepare(tmp_path)
    result = maybe_drawdown_halt(
        peak=100_000,
        total_asset=87_800,
        cash=10_000,
        market_value=77_800,
        initial_cash=100_000,
        account_id="paper:demo",
        strategy_id="etf_ma_rotate",
        trade_date="2024-01-02",
        settings=settings,
    )
    assert result["halt"] is True
    from asqt.ops import LocalAlertService

    rows = LocalAlertService(settings).list_alerts(status="open")
    drawdown = [row for row in rows if row["category"] == "drawdown"]
    assert drawdown
    detail = json.loads(drawdown[0]["detail"])
    assert detail["schema"] == "asqt.alert.v1"
    assert detail["peak_asset"] == 100_000
    assert detail["total_asset"] == 87_800
    assert detail["cash"] == 10_000
    assert detail["strategy_id"] == "etf_ma_rotate"


def test_hydrate_legacy_drawdown_never_shows_raw_dd(tmp_path):
    from asqt.alert_format import format_alert_full, hydrate_alert_row
    from asqt.db import execute
    from asqt.ops import LocalAlertService

    settings, _engine, _service = _prepare(tmp_path)
    execute(
        """
        INSERT INTO account_snapshot
            (account_id, trade_date, cash, market_value, total_asset, position_detail, reconcile_diff)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "paper:stock_momentum_topk",
            "2026-08-31",
            58086.6924,
            31035.0,
            89121.6924,
            json.dumps({"peak_asset": 101338.1956, "initial_cash": 100000.0}, ensure_ascii=False),
            None,
        ),
        settings=settings,
    )
    LocalAlertService(settings).raise_alert(
        "critical",
        "drawdown",
        "max drawdown stop",
        "dd=-0.120552",
    )
    rows = LocalAlertService(settings).list_alerts(status="open")
    drawdown = next(row for row in rows if row["category"] == "drawdown")
    detail = json.loads(drawdown["detail"])
    assert detail["peak_asset"] == 101338.1956
    assert detail["cash"] == 58086.6924
    full = format_alert_full(drawdown)
    assert "原始字段" not in full
    assert "dd=" not in full
    assert "账户峰值" in full
    assert "现金" in full
    # already hydrated row stays stable
    again = hydrate_alert_row(drawdown, settings=settings)
    assert again["detail"] == drawdown["detail"]
