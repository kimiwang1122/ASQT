"""Backtest attribution. Paper vs backtest wait for P3 fills."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import initialize_database, query_all
from asqt.research_engine import LocalResearchEngine, data_version_for
from asqt.storage import read_market_daily
from asqt.strategies import STRATEGY_SPECS, adj_close, weights_for


class LocalReviewService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def build_daily_review(self, trade_date: str | None = None) -> dict[str, Any]:
        items = [self.attribute_backtest(strategy_id) for strategy_id in STRATEGY_SPECS]
        return {
            "asof": trade_date,
            "items": items,
            "paper_vs_backtest": {
                "available": False,
                "reason": "no_paper_fills",
                "detail": "模拟成交尚未落地，无法算回测与模拟偏差",
            },
        }

    def attribute_backtest(self, strategy_id: str) -> dict[str, Any]:
        if strategy_id not in STRATEGY_SPECS:
            raise ValueError(f"unknown strategy: {strategy_id}")
        rows = read_market_daily(settings=self.settings)
        quality = _quality_gate(self.settings)
        if not rows:
            return _empty_attr(strategy_id, "no_market_daily", quality)
        if not quality.get("trade_allowed", False):
            return _empty_attr(strategy_id, "quality_block", quality)
        dates = sorted({str(row["trade_date"]) for row in rows})
        if len(dates) < 4:
            return _empty_attr(strategy_id, "too_few_dates", quality)

        engine = LocalResearchEngine(self.settings)
        in_sample_end = engine._in_sample_end(rows)
        limits = query_all("SELECT * FROM limit_suspension", settings=self.settings)
        by_date_symbol = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
        bucket: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "contribution": 0.0,
                "is_contribution": 0.0,
                "oos_contribution": 0.0,
                "days": 0.0,
                "weight_sum": 0.0,
            }
        )
        nav = 1.0
        last_weights: dict[str, float] = {}
        for index, signal_date in enumerate(dates[:-1]):
            fill_date = dates[index + 1]
            weights = weights_for(strategy_id, rows, signal_date, limits=limits)
            last_weights = weights
            period_return = 0.0
            for symbol, weight in weights.items():
                left = by_date_symbol.get((signal_date, symbol))
                right = by_date_symbol.get((fill_date, symbol))
                if not left or not right:
                    continue
                start_px = adj_close(left)
                if start_px <= 0:
                    continue
                add = weight * (adj_close(right) / start_px - 1.0)
                period_return += add
                item = bucket[symbol]
                item["contribution"] += add
                item["days"] += 1
                item["weight_sum"] += weight
                if fill_date <= in_sample_end:
                    item["is_contribution"] += add
                else:
                    item["oos_contribution"] += add
            nav *= 1.0 + period_return

        by_symbol = []
        for symbol, item in bucket.items():
            days = int(item["days"])
            by_symbol.append(
                {
                    "symbol": symbol,
                    "contribution": round(item["contribution"], 10),
                    "is_contribution": round(item["is_contribution"], 10),
                    "oos_contribution": round(item["oos_contribution"], 10),
                    "days": days,
                    "avg_weight": round(item["weight_sum"] / days, 10) if days else 0.0,
                }
            )
        by_symbol.sort(key=lambda row: row["contribution"], reverse=True)
        is_sum = round(sum(row["is_contribution"] for row in by_symbol), 10)
        oos_sum = round(sum(row["oos_contribution"] for row in by_symbol), 10)
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "kind": STRATEGY_SPECS[strategy_id]["kind"],
            "parameter_set_id": STRATEGY_SPECS[strategy_id]["parameter_set_id"],
            "data_version": data_version_for(rows),
            "in_sample_end": in_sample_end,
            "nav": round(nav, 10),
            "total_return": round(nav - 1.0, 10),
            "additive_return": round(is_sum + oos_sum, 10),
            "is_contribution": is_sum,
            "oos_contribution": oos_sum,
            "by_symbol": by_symbol,
            "top": by_symbol[:5],
            "bottom": list(reversed(by_symbol[-5:])) if by_symbol else [],
            "last_weights": last_weights,
            "quality": {"trade_allowed": True, "issue_count": quality.get("issue_count", 0)},
            "paper_vs_backtest": {
                "available": False,
                "reason": "no_paper_fills",
                "detail": "模拟成交尚未落地，无法算回测与模拟偏差",
            },
        }


def _quality_gate(settings: Settings) -> dict[str, Any]:
    rows = query_all(
        """
        SELECT COUNT(*) AS n FROM quality_issue
        WHERE dataset = 'market_daily' AND status = 'open' AND severity = 'block'
        """,
        settings=settings,
    )
    count = int(rows[0]["n"]) if rows else 0
    return {"trade_allowed": count == 0, "issue_count": count}


def _empty_attr(strategy_id: str, reason: str, quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "strategy_id": strategy_id,
        "kind": STRATEGY_SPECS[strategy_id]["kind"],
        "reason": reason,
        "by_symbol": [],
        "top": [],
        "bottom": [],
        "last_weights": {},
        "quality": {
            "trade_allowed": quality.get("trade_allowed"),
            "issue_count": quality.get("issue_count", 0),
        },
        "paper_vs_backtest": {
            "available": False,
            "reason": "no_paper_fills",
            "detail": "模拟成交尚未落地，无法算回测与模拟偏差",
        },
    }
