"""Backtest attribution plus paper vs backtest after fills."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import initialize_database, query_all
from asqt.paper import account_id_for, paper_curve
from asqt.research_engine import LocalResearchEngine, data_version_for
from asqt.storage import read_market_daily
from asqt.strategies import (
    STRATEGY_SPECS,
    adj_close,
    market_by_symbol,
    suspended_keys,
    weights_for,
)


class LocalReviewService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def build_daily_review(self, trade_date: str | None = None) -> dict[str, Any]:
        items = [self.attribute_backtest(strategy_id) for strategy_id in STRATEGY_SPECS]
        paper = self.paper_vs_backtest()
        return {
            "asof": trade_date,
            "items": items,
            "paper_vs_backtest": paper,
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
        grouped = market_by_symbol(rows)
        suspended = suspended_keys(limits)
        weight_cache: dict[str, dict[str, float]] = {}

        def cached_weights(asof: str) -> dict[str, float]:
            hit = weight_cache.get(asof)
            if hit is None:
                hit = weights_for(
                    strategy_id,
                    rows,
                    asof,
                    limits=limits,
                    market_by_symbol=grouped,
                    suspended=suspended,
                )
                weight_cache[asof] = hit
            return hit

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
            weights = cached_weights(signal_date)
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
        fill_dates = dates[1:]
        is_days = sum(1 for day in fill_dates if day <= in_sample_end)
        oos_days = len(fill_dates) - is_days
        additive = is_sum + oos_sum
        is_share = round(is_sum / additive, 10) if abs(additive) > 1e-12 else None
        oos_share = round(oos_sum / additive, 10) if abs(additive) > 1e-12 else None
        top_is = sorted(by_symbol, key=lambda row: row["is_contribution"], reverse=True)[:5]
        top_oos = sorted(by_symbol, key=lambda row: row["oos_contribution"], reverse=True)[:5]
        bottom_oos = sorted(by_symbol, key=lambda row: row["oos_contribution"])[:5]
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "kind": STRATEGY_SPECS[strategy_id]["kind"],
            "parameter_set_id": STRATEGY_SPECS[strategy_id]["parameter_set_id"],
            "params": dict(STRATEGY_SPECS[strategy_id]["params"]),
            "data_version": data_version_for(rows),
            "sample": {"start": dates[0], "end": dates[-1], "n_sessions": len(dates)},
            "in_sample_end": in_sample_end,
            "is_days": is_days,
            "oos_days": oos_days,
            "is_share": is_share,
            "oos_share": oos_share,
            "nav": round(nav, 10),
            "total_return": round(nav - 1.0, 10),
            "additive_return": round(additive, 10),
            "is_contribution": is_sum,
            "oos_contribution": oos_sum,
            "by_symbol": by_symbol,
            "top": by_symbol[:5],
            "top_is": top_is,
            "top_oos": top_oos,
            "bottom": list(reversed(by_symbol[-5:])) if by_symbol else [],
            "bottom_oos": bottom_oos,
            "last_weights": last_weights,
            "quality": {"trade_allowed": True, "issue_count": quality.get("issue_count", 0)},
            "paper_vs_backtest": self.paper_vs_backtest(
                strategy_id,
                rows=rows,
                dates=dates,
                by_date_symbol=by_date_symbol,
                limits=limits,
                grouped=grouped,
                suspended=suspended,
                weight_cache=weight_cache,
            ),
        }

    def paper_vs_backtest(
        self,
        strategy_id: str | None = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        dates: list[str] | None = None,
        by_date_symbol: dict[tuple[str, str], dict[str, Any]] | None = None,
        limits: list[dict[str, Any]] | None = None,
        grouped: dict[str, list[dict[str, Any]]] | None = None,
        suspended: set[tuple[str, str]] | None = None,
        weight_cache: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        ids = [strategy_id] if strategy_id else list(STRATEGY_SPECS)
        market = rows if rows is not None else read_market_daily(settings=self.settings)
        calendar = dates if dates is not None else sorted({str(row["trade_date"]) for row in market})
        lookup = by_date_symbol or {(str(row["trade_date"]), str(row["symbol"])): row for row in market}
        halt_rows = limits if limits is not None else query_all("SELECT * FROM limit_suspension", settings=self.settings)
        book = grouped if grouped is not None else market_by_symbol(market)
        halted = suspended if suspended is not None else suspended_keys(halt_rows)
        items = []
        for sid in ids:
            curve = paper_curve(sid, self.settings)
            if len(curve) < 2:
                continue
            cache = weight_cache if strategy_id == sid and weight_cache is not None else {}

            def cached_weights(asof: str, current_id: str = sid, local_cache: dict[str, dict[str, float]] = cache) -> dict[str, float]:
                hit = local_cache.get(asof)
                if hit is None:
                    hit = weights_for(
                        current_id,
                        market,
                        asof,
                        limits=halt_rows,
                        market_by_symbol=book,
                        suspended=halted,
                    )
                    local_cache[asof] = hit
                return hit

            fill_dates = [str(item["trade_date"]) for item in curve]
            start = fill_dates[0]
            prior = [day for day in calendar if day < start]
            if not prior:
                continue
            signal_dates = [prior[-1], *fill_dates[:-1]]
            nav = 1.0
            bt_points = []
            for signal_date, fill_date in zip(signal_dates, fill_dates):
                weights = cached_weights(signal_date)
                period = 0.0
                for symbol, weight in weights.items():
                    left = lookup.get((signal_date, symbol))
                    right = lookup.get((fill_date, symbol))
                    if not left or not right:
                        continue
                    start_px = adj_close(left)
                    if start_px <= 0:
                        continue
                    period += weight * (adj_close(right) / start_px - 1.0)
                nav *= 1.0 + period
                bt_points.append({"trade_date": fill_date, "nav": nav})
            initial = float(curve[0]["total_asset"])
            paper_points = [
                {"trade_date": item["trade_date"], "nav": float(item["total_asset"]) / initial}
                for item in curve
            ]
            gaps = []
            bt_by_date = {item["trade_date"]: item["nav"] for item in bt_points}
            for point in paper_points:
                bt_nav = bt_by_date.get(point["trade_date"])
                if bt_nav:
                    gaps.append(abs(point["nav"] / bt_nav - 1.0))
            items.append(
                {
                    "strategy_id": sid,
                    "n_days": len(curve),
                    "paper_return": round(float(curve[-1]["total_asset"]) / initial - 1.0, 10),
                    "backtest_return": round(nav - 1.0, 10),
                    "max_abs_nav_gap": round(max(gaps) if gaps else 0.0, 10),
                    "account_id": account_id_for(sid),
                }
            )
        if not items:
            return {
                "available": False,
                "reason": "no_paper_fills",
                "detail": "模拟成交尚未落地，无法算回测与模拟偏差",
                "items": [],
            }
        return {"available": True, "reason": None, "detail": None, "items": items}


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
