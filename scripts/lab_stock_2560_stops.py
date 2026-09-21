#!/usr/bin/env python3
"""Grid take-profit / stop-loss on each stock_2560 lab base, fee-aware ledger.

Usage:
  uv run python scripts/lab_stock_2560_stops.py
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asqt.config import get_settings
from asqt.db import query_all
from asqt.factors import rule_2560_timeline
from asqt.ops import paper_account_config
from asqt.paper import (
    GROSS_LIMIT,
    LOT,
    MAX_WEIGHT,
    SLIPPAGE,
    STAMP_RATE,
    _at_limit,
    _fees,
    _fill_price,
    _lot,
    _nav,
    _projected_gross,
    apply_inferred_splits,
)
from asqt.research_engine import _nav_metrics
from asqt.selectors import clip_weights
from asqt.storage import read_market_daily
from asqt.lab_params import STOCK_2560_PRESETS
from asqt.strategies import STOCK_2560, STRATEGY_SPECS, market_by_symbol, suspended_keys
from asqt.tune import stock_2560_short_id, suggest_parameter_set_id

STOPS = (0.0, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15)
TAKES = (0.0, 0.10, 0.15, 0.20, 0.30, 0.40, 0.60)
INITIAL = 100_000.0


def _bases() -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for raw in STOCK_2560_PRESETS:
        params = dict(STRATEGY_SPECS[STOCK_2560]["params"])
        params.update(raw)
        params["stop_loss"] = 0.0
        params["take_profit"] = 0.0
        psid = suggest_parameter_set_id(STOCK_2560, params)
        if psid in seen:
            continue
        seen.add(psid)
        out.append(params)
    return out


class Book:
    def __init__(self, rows, limits, commission_rate: float, base: dict):
        self.base = dict(base)
        self.commission_rate = commission_rate
        self.by_key = {(str(r["trade_date"]), str(r["symbol"])): r for r in rows}
        self.limit_map = {(str(r["trade_date"]), str(r["symbol"])): r for r in limits}
        self.halted = suspended_keys(limits)
        grouped = market_by_symbol(rows)
        tl_kw = {
            "ma_fast": int(base["ma_fast"]),
            "ma_slow": int(base["ma_slow"]),
            "vol_fast": int(base["vol_fast"]),
            "vol_slow": int(base["vol_slow"]),
            "pullback_band": float(base["pullback_band"]),
        }
        self.timelines = {}
        self.asof_index = {}
        for symbol, series in grouped.items():
            self.timelines[symbol] = rule_2560_timeline(series, **tl_kw)
            self.asof_index[symbol] = {str(row["trade_date"]): i for i, row in enumerate(series)}
        self.top_k = int(base["top_k"])
        self.max_weight = float(base["max_weight"])
        self.gross_limit = float(base["gross_limit"])

    def weights(self, signal_date: str, held: list[str]) -> dict[str, float]:
        states = {}
        for symbol, index_map in self.asof_index.items():
            if (symbol, signal_date) in self.halted:
                continue
            idx = index_map.get(signal_date)
            if idx is None:
                continue
            state = self.timelines[symbol][idx]
            if state is not None:
                states[symbol] = state
        keep = []
        for symbol in held:
            if symbol in states and symbol not in keep:
                keep.append(symbol)
            if len(keep) >= self.top_k:
                break
        slots = self.top_k - len(keep)
        entries = sorted(
            ((sc, sym) for sym, (ph, sc) in states.items() if ph == "entry" and sym not in keep),
            reverse=True,
        )
        if not keep and slots == self.top_k:
            ranked = sorted(((sc, sym) for sym, (_p, sc) in states.items()), reverse=True)
            picked = [sym for _sc, sym in ranked[: self.top_k]]
        else:
            picked = keep + [sym for _sc, sym in entries[:slots]]
        if not picked:
            return {}
        weight = 1.0 / len(picked)
        return clip_weights({sym: weight for sym in picked}, self.max_weight, self.gross_limit)

    def _blocked(self, trade_date: str, symbol: str, side: str, open_px: float) -> bool:
        lim = self.limit_map.get((trade_date, symbol))
        if not lim:
            return False
        if int(lim.get("is_suspended") or 0) == 1:
            return True
        if side == "BUY" and _at_limit(open_px, lim.get("limit_up")):
            return True
        if side == "SELL" and _at_limit(open_px, lim.get("limit_down")):
            return True
        return False

    def run(self, dates: list[str], *, stop_loss: float, take_profit: float) -> dict:
        """Match PaperOrderService: live held, stop zeros, buy/sell order, whole-order reject."""
        take = max(0.0, float(take_profit))
        stop = -abs(float(stop_loss)) if float(stop_loss) > 0 else 0.0
        cap = MAX_WEIGHT["stock"]
        state = {"cash": INITIAL, "positions": {}, "tradable": {}}
        fees_total = 0.0
        curve = []
        peak_asset = INITIAL
        first_invested = None
        for i in range(1, len(dates)):
            signal_date, trade_date = dates[i - 1], dates[i]
            apply_inferred_splits(state, self.by_key, signal_date, trade_date)
            state["tradable"] = {
                symbol: int(item["qty"])
                for symbol, item in state["positions"].items()
                if int(item.get("qty") or 0) > 0
            }
            held = [sym for sym, item in state["positions"].items() if int(item.get("qty") or 0) > 0]
            weights = self.weights(signal_date, held)
            for symbol, item in list(state["positions"].items()):
                bar = self.by_key.get((signal_date, symbol))
                cost = float(item.get("cost") or 0)
                if not bar or cost <= 0:
                    continue
                pnl = float(bar["close"]) / cost - 1.0
                if (take > 0 and pnl >= take) or (stop < 0 and pnl <= stop):
                    weights[symbol] = 0.0
            nav = _nav(state, self.by_key, signal_date)
            intended: dict[str, float] = dict(weights)
            day_fees = 0.0
            for symbol, weight in list(intended.items()):
                bar_signal = self.by_key.get((signal_date, symbol))
                bar_fill = self.by_key.get((trade_date, symbol))
                if not bar_signal or not bar_fill:
                    continue
                px = float(bar_signal["close"])
                if px <= 0:
                    continue
                target = _lot(weight * nav / px)
                cur = int(state["positions"].get(symbol, {}).get("qty") or 0)
                delta = target - cur
                if delta == 0:
                    continue
                open_px = float(bar_fill["open"])
                side = "BUY" if delta > 0 else "SELL"
                if self._blocked(trade_date, symbol, side, open_px):
                    continue
                if side == "SELL":
                    qty = _lot(min(-delta, int(state["tradable"].get(symbol, 0))))
                    if qty < LOT:
                        continue
                    fill_px = _fill_price(open_px, "SELL")
                    notional = qty * fill_px
                    fee = _fees(symbol, "SELL", notional, commission_rate=self.commission_rate)
                    state["cash"] += notional - fee
                    day_fees += fee
                    left = cur - qty
                    if left <= 0:
                        state["positions"].pop(symbol, None)
                        state["tradable"].pop(symbol, None)
                    else:
                        state["positions"][symbol]["qty"] = left
                        state["tradable"][symbol] = max(0, int(state["tradable"].get(symbol, 0)) - qty)
                    continue
                qty = _lot(delta)
                if qty < LOT:
                    continue
                fill_px = _fill_price(open_px, "BUY")
                notional = qty * fill_px
                fee = _fees(symbol, "BUY", notional, commission_rate=self.commission_rate)
                if weight > cap + 1e-9 or (nav and notional / nav > cap + 1e-9):
                    continue
                if _projected_gross(state, symbol, qty, fill_px, nav) > GROSS_LIMIT + 1e-9:
                    continue
                if state["cash"] < notional + fee:
                    continue
                state["cash"] -= notional + fee
                day_fees += fee
                pos = state["positions"].setdefault(symbol, {"qty": 0, "cost": 0.0})
                new_qty = int(pos["qty"]) + qty
                pos["cost"] = (float(pos["cost"]) * int(pos["qty"]) + notional) / new_qty
                pos["qty"] = new_qty
            for symbol, item in list(state["positions"].items()):
                if symbol in intended:
                    continue
                bar_fill = self.by_key.get((trade_date, symbol))
                if not bar_fill:
                    continue
                open_px = float(bar_fill["open"])
                if self._blocked(trade_date, symbol, "SELL", open_px):
                    continue
                qty = _lot(min(int(item["qty"]), int(state["tradable"].get(symbol, 0))))
                if qty < LOT:
                    continue
                fill_px = _fill_price(open_px, "SELL")
                notional = qty * fill_px
                fee = _fees(symbol, "SELL", notional, commission_rate=self.commission_rate)
                state["cash"] += notional - fee
                day_fees += fee
                left = int(item["qty"]) - qty
                if left <= 0:
                    state["positions"].pop(symbol, None)
                    state["tradable"].pop(symbol, None)
                else:
                    state["positions"][symbol]["qty"] = left
                    state["tradable"][symbol] = max(0, int(state["tradable"].get(symbol, 0)) - qty)
            asset = _nav(state, self.by_key, trade_date)
            if first_invested is None and state["positions"]:
                first_invested = trade_date
            peak_asset = max(peak_asset, asset)
            fees_total += day_fees
            curve.append({"trade_date": trade_date, "nav": asset / INITIAL, "asset": asset})
        metrics = _nav_metrics(curve, start_nav=1.0)
        params = {**self.base, "stop_loss": float(stop_loss), "take_profit": float(take_profit)}
        end_asset = float(curve[-1]["asset"]) if curve else INITIAL
        return {
            "parameter_set_id": suggest_parameter_set_id(STOCK_2560, params),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "total_return": round(end_asset / INITIAL - 1.0, 6) if curve else None,
            "peak_return": round(peak_asset / INITIAL - 1.0, 6),
            "max_drawdown": metrics.get("max_drawdown"),
            "end_asset": round(end_asset, 2),
            "fees": round(fees_total, 2),
            "first_invested": first_invested,
        }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="substring of short or full parameter_set_id")
    args = parser.parse_args()
    needle = str(args.only or "").strip()
    settings = get_settings()
    rows = read_market_daily(settings=settings)
    dates = sorted({str(r["trade_date"]) for r in rows if str(r["trade_date"]) >= "2018-01-01"})
    limits = query_all("SELECT * FROM limit_suspension", settings=settings)
    rate = float(paper_account_config(settings)["commission_rate"])
    bases = _bases()
    cells = list(itertools.product(STOPS, TAKES))
    planned = []
    for base in bases:
        for sl, tp in cells:
            params = {**base, "stop_loss": sl, "take_profit": tp}
            psid = suggest_parameter_set_id(STOCK_2560, params)
            short = stock_2560_short_id(params)
            if needle and needle not in psid and needle not in short:
                continue
            planned.append((base, sl, tp, psid))
    total = len(planned)
    print(
        f"cells={total}  window {dates[0]}→{dates[-1]}  "
        f"commission={rate} stamp={STAMP_RATE} slip={SLIPPAGE}  paper-matched fills",
        flush=True,
    )
    ranked = []
    books: dict[str, Book] = {}
    for i, (base, sl, tp, psid) in enumerate(planned, 1):
        key = suggest_parameter_set_id(STOCK_2560, {**base, "stop_loss": 0.0, "take_profit": 0.0})
        if key not in books:
            books[key] = Book(rows, limits, rate, base)
        row = books[key].run(dates, stop_loss=sl, take_profit=tp)
        ranked.append(row)
        if i == 1 or i % 14 == 0 or i == total:
            best = max(r["total_return"] for r in ranked)
            print(
                f"  {i}/{total} best={best:+.2%}  last sl={sl:.0%} tp={tp:.0%} "
                f"{row['total_return']:+.2%} peak={row['peak_return']:+.2%}",
                flush=True,
            )
    ranked.sort(key=lambda r: (r["total_return"], -(abs(r["max_drawdown"] or 0))), reverse=True)
    by_base = {}
    for row in ranked:
        key = row["parameter_set_id"].split(".sl")[0] if ".sl" in row["parameter_set_id"] else row["parameter_set_id"]
        by_base.setdefault(key, []).append(row)
    out = {
        "window": [dates[0], dates[-1]],
        "note": "in-memory ledger (not PaperBroker); paper run is source of truth",
        "grid_size": len(ranked),
        "top": ranked[:20],
        "best_per_base": {key: rows[0] for key, rows in by_base.items()},
    }
    path = Path("data/experiment/tune/stock_2560_all_stops_grid.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nTOP")
    for row in ranked[:15]:
        print(
            f"  {row['total_return']:+.2%}  peak={row['peak_return']:+.2%}  "
            f"dd={row['max_drawdown']:+.2%}  fees={row['fees']:,.0f}  "
            f"sl={row['stop_loss']:.0%} tp={row['take_profit']:.0%}  {row['parameter_set_id']}"
        )
    print("\nBEST PER BASE")
    for key, row in out["best_per_base"].items():
        print(f"  {row['total_return']:+.2%}  {row['parameter_set_id']}")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
