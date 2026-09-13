"""PaperBroker, ledger, and consecutive paper replay."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from asqt.config import Settings, ensure_runtime_dirs, get_settings
from asqt.db import connect, execute, initialize_database, query_all
from asqt.ops import (
    close_flatten_incomplete_alerts,
    close_strategy_halt_alerts,
    kill_engaged,
    maybe_drawdown_halt,
    maybe_flatten_incomplete_alert,
    paper_account_config,
    quality_gate,
    reset_portfolio_peak,
    set_kill_switch,
)
from asqt.research_engine import LocalStrategyService
from asqt.storage import read_market_daily
from asqt.strategies import STRATEGY_SPECS
from asqt.symbols import infer_instrument_type

ACCOUNT_PREFIX = "paper:"
INITIAL_CASH = 1_000_000.0
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_RATE = 0.0005
TRANSFER_RATE = 0.00001
SLIPPAGE = 0.0005
LOT = 100
GROSS_LIMIT = 0.95
TAKE_PROFIT = 0.20
STOP_LOSS = -0.08
MAX_WEIGHT = {"stock": 0.10, "etf": 0.20}
PAPER_LOCK_ID = "paper-run"
PAPER_LOCK_MINUTES = 120
PAPER_BUSY_MESSAGE = "模拟盘运行中，请勿重复提交"

_paper_cash_overrides: dict[str, float] = {}
_paper_cash_override_lock = threading.Lock()


def _cash_override_key(settings: Settings, strategy_id: str) -> str:
    return f"{settings.database_path}::{strategy_id}"


def _set_cash_override(settings: Settings, strategy_id: str, cash: float) -> None:
    with _paper_cash_override_lock:
        _paper_cash_overrides[_cash_override_key(settings, strategy_id)] = float(cash)


def _clear_cash_overrides(settings: Settings, strategy_ids: list[str]) -> None:
    with _paper_cash_override_lock:
        for sid in strategy_ids:
            _paper_cash_overrides.pop(_cash_override_key(settings, sid), None)


def _get_cash_override(settings: Settings | None, strategy_id: str | None) -> float | None:
    if settings is None or not strategy_id:
        return None
    with _paper_cash_override_lock:
        value = _paper_cash_overrides.get(_cash_override_key(settings, strategy_id))
    return None if value is None else float(value)


def split_parallel_cash(total: float, n: int) -> list[float]:
    """Split total into n parts: floor(total/n) each, remainder to the first book."""
    if n <= 0:
        raise ValueError("n must be positive")
    total = float(total)
    base = math.floor(total / n)
    amounts = [float(base)] * n
    amounts[0] = float(total - base * (n - 1))
    return amounts


def paper_admitted_ids(settings: Settings | None = None) -> list[str]:
    """Paper-status strategies in stable STRATEGY_SPECS order."""
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    versions = LocalStrategyService(settings)
    ids: list[str] = []
    for sid in STRATEGY_SPECS:
        current = versions.current_version(sid)
        if current and current.get("status") == "paper":
            ids.append(sid)
    return ids


def portfolio_book_cash_map(
    settings: Settings | None = None,
    *,
    universe: list[str] | None = None,
) -> dict[str, float]:
    """Map each portfolio book to its share of configured initial_cash."""
    settings = ensure_runtime_dirs(settings or get_settings())
    ids = list(universe) if universe is not None else paper_admitted_ids(settings)
    if not ids:
        return {}
    total = float(paper_account_config(settings)["initial_cash"])
    return dict(zip(ids, split_parallel_cash(total, len(ids))))


def _prepare_shared_book_cash(
    *,
    ids: list[str],
    job_key: str,
    settings: Settings,
    reason: str,
) -> list[float]:
    """Reset run targets and fund each book as a share of portfolio capital.

    Settings「初始资金」is portfolio capital. Split across strategies in *this* run
    (selected runners), so a solo run of one strategy gets the full amount.
    """
    del job_key  # callers still pass job_key for lock/audit context
    universe = list(ids)
    if not universe:
        raise ValueError("paper run requires at least one strategy")
    cash_map = portfolio_book_cash_map(settings, universe=universe)
    for sid in ids:
        _reset_paper_account_locked(
            strategy_id=sid,
            actor="system",
            reason=reason,
            settings=settings,
            clear_kill=False,
        )
    reset_portfolio_peak(settings)
    for sid in ids:
        _set_cash_override(settings, sid, cash_map[sid])
    return [float(cash_map[sid]) for sid in ids]


class PaperBusy(Exception):
    """Another paper-run or reset is already holding the ledger lock."""


def account_id_for(strategy_id: str) -> str:
    return f"{ACCOUNT_PREFIX}{strategy_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def acquire_paper_run_lock(settings: Settings | None = None, *, holder: str = "api") -> str:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    run_id = str(uuid4())
    now = _now()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=PAPER_LOCK_MINUTES)).isoformat()
    conn = connect(settings)
    try:
        conn.execute("BEGIN IMMEDIATE")
        lock = conn.execute(
            "SELECT run_id, expires_at FROM data_sync_lock WHERE lock_id = ?",
            (PAPER_LOCK_ID,),
        ).fetchone()
        if lock and str(lock["expires_at"] or "") > now:
            conn.rollback()
            raise PaperBusy(PAPER_BUSY_MESSAGE)
        if lock:
            conn.execute(
                """
                UPDATE data_sync_lock
                SET run_id = ?, holder = ?, acquired_at = ?, expires_at = ?
                WHERE lock_id = ?
                """,
                (run_id, holder, now, expires, PAPER_LOCK_ID),
            )
        else:
            conn.execute(
                """
                INSERT INTO data_sync_lock (lock_id, run_id, holder, acquired_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (PAPER_LOCK_ID, run_id, holder, now, expires),
            )
        conn.commit()
    except PaperBusy:
        raise
    except sqlite3.IntegrityError:
        conn.rollback()
        raise PaperBusy(PAPER_BUSY_MESSAGE)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return run_id


def release_paper_run_lock(settings: Settings | None, run_id: str) -> None:
    execute(
        "DELETE FROM data_sync_lock WHERE lock_id = ? AND run_id = ?",
        (PAPER_LOCK_ID, run_id),
        settings=settings,
    )


def paper_run_locked(settings: Settings | None = None) -> bool:
    now = _now()
    rows = query_all(
        "SELECT expires_at FROM data_sync_lock WHERE lock_id = ?",
        (PAPER_LOCK_ID,),
        settings=settings,
    )
    return bool(rows and str(rows[0]["expires_at"] or "") > now)


@contextmanager
def paper_exclusive(settings: Settings | None = None, *, holder: str = "api"):
    settings = ensure_runtime_dirs(settings or get_settings())
    token = acquire_paper_run_lock(settings, holder=holder)
    try:
        yield token
    finally:
        release_paper_run_lock(settings, token)


def _lot(qty: float) -> int:
    return int(qty // LOT) * LOT


def _fees(symbol: str, side: str, notional: float, *, commission_rate: float | None = None) -> float:
    rate = COMMISSION_RATE if commission_rate is None else float(commission_rate)
    commission = max(COMMISSION_MIN, abs(notional) * rate)
    stamp = abs(notional) * STAMP_RATE if side == "SELL" else 0.0
    transfer = abs(notional) * TRANSFER_RATE if symbol.endswith(".SH") else 0.0
    return round(commission + stamp + transfer, 4)


def _fill_price(open_px: float, side: str) -> float:
    if side == "BUY":
        return round(open_px * (1.0 + SLIPPAGE), 6)
    return round(open_px * (1.0 - SLIPPAGE), 6)


def _empty_state(
    settings: Settings | None = None,
    *,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    # Unfunded / reset books stay at 0 until a run sets per-book overrides via
    # _prepare_shared_book_cash. Do not default to full portfolio initial_cash.
    override = _get_cash_override(settings, strategy_id)
    cash = float(override) if override is not None else 0.0
    return {
        "cash": cash,
        "initial_cash": cash,
        "peak_asset": cash,
        "positions": {},
        "tradable": {},
        "halted": False,
        "flatten_pending": False,
        "halt_reason": None,
        # Durable halt before this session's mutations (build_orders may set halted
        # in-memory before save; that must not suppress the first Feishu alert).
        "_prior_halted": False,
    }


def _open_position_qty(state: dict[str, Any]) -> int:
    return sum(int(item.get("qty") or 0) for item in (state.get("positions") or {}).values())


def sync_halt_lifecycle(state: dict[str, Any]) -> str:
    """Normalize halt flags and return UI status: active | flatten_pending | halted."""
    open_qty = _open_position_qty(state)
    if state.get("halted") or state.get("flatten_pending"):
        state["halted"] = True
        state["flatten_pending"] = open_qty > 0
        return "flatten_pending" if state["flatten_pending"] else "halted"
    return "active"


def halt_status_of(state: dict[str, Any] | None) -> str:
    if not state:
        return "active"
    if state.get("flatten_pending") or (
        state.get("halted") and _open_position_qty(state) > 0
    ):
        return "flatten_pending"
    if state.get("halted"):
        return "halted"
    return "active"


class PaperBroker:
    channel_id = "paper"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def channel_status(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            # Channel stays available under kill so liquidation sells can still fill.
            "available": True,
            "kill_switch": kill_engaged(self.settings),
        }

    def query_order(self, order_id: str) -> dict[str, Any]:
        rows = query_all(
            "SELECT * FROM standard_order WHERE order_id = ?",
            (order_id,),
            settings=self.settings,
        )
        if not rows:
            raise KeyError(order_id)
        return rows[0]

    def cancel(self, order_id: str) -> dict[str, Any]:
        order = self.query_order(order_id)
        if order["status"] in {"filled", "rejected", "cancelled"}:
            return order
        execute(
            "UPDATE standard_order SET status = 'cancelled', updated_at = ? WHERE order_id = ?",
            (_now(), order_id),
            settings=self.settings,
        )
        order["status"] = "cancelled"
        return order

    def submit(self, order: dict[str, Any]) -> dict[str, Any]:
        order_id = order["order_id"]
        now = _now()
        execute(
            "UPDATE standard_order SET status = 'submitted', updated_at = ? WHERE order_id = ?",
            (now, order_id),
            settings=self.settings,
        )
        return self.query_order(order_id)

    def fill(self, order: dict[str, Any], *, price: float, trade_time: str) -> dict[str, Any]:
        qty = int(order["quantity"])
        notional = qty * price
        fee = _fees(
            order["symbol"],
            order["side"],
            notional,
            commission_rate=paper_account_config(self.settings)["commission_rate"],
        )
        fill_id = str(uuid4())
        execute(
            """
            INSERT INTO execution_fill
                (fill_id, order_id, broker_order_id, symbol, side, filled_qty, filled_price, fee, status, trade_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'filled', ?)
            """,
            (
                fill_id,
                order["order_id"],
                f"paper-{order['order_id'][:8]}",
                order["symbol"],
                order["side"],
                qty,
                price,
                fee,
                trade_time,
            ),
            settings=self.settings,
        )
        execute(
            "UPDATE standard_order SET status = 'filled', updated_at = ? WHERE order_id = ?",
            (_now(), order["order_id"]),
            settings=self.settings,
        )
        return {
            "fill_id": fill_id,
            "order_id": order["order_id"],
            "filled_qty": qty,
            "filled_price": price,
            "fee": fee,
            "status": "filled",
        }


class PaperLedger:
    def __init__(self, strategy_id: str, settings: Settings | None = None) -> None:
        self.strategy_id = strategy_id
        self.account_id = account_id_for(strategy_id)
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)

    def load(self, *, before: str | None = None) -> dict[str, Any]:
        if before:
            rows = query_all(
                """
                SELECT * FROM account_snapshot
                WHERE account_id = ? AND trade_date < ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (self.account_id, before),
                settings=self.settings,
            )
        else:
            rows = query_all(
                """
                SELECT * FROM account_snapshot
                WHERE account_id = ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (self.account_id,),
                settings=self.settings,
            )
        if not rows:
            return _empty_state(self.settings, strategy_id=self.strategy_id)
        detail = json.loads(rows[0]["position_detail"] or "{}")
        state = _empty_state(self.settings, strategy_id=self.strategy_id)
        state["cash"] = float(rows[0]["cash"])
        override = _get_cash_override(self.settings, self.strategy_id)
        fallback = float(
            override if override is not None else paper_account_config(self.settings)["initial_cash"]
        )
        state["initial_cash"] = float(detail.get("initial_cash", fallback))
        state["peak_asset"] = float(detail.get("peak_asset", rows[0]["total_asset"]))
        state["positions"] = {
            symbol: {
                "qty": int(item["qty"]),
                "cost": float(item["cost"]),
                "market_price": float(item.get("market_price") or item["cost"]),
            }
            for symbol, item in (detail.get("positions") or {}).items()
        }
        state["tradable"] = {symbol: int(qty) for symbol, qty in (detail.get("tradable") or {}).items()}
        if not state["tradable"]:
            state["tradable"] = {symbol: item["qty"] for symbol, item in state["positions"].items()}
        state["halted"] = bool(detail.get("halted"))
        state["flatten_pending"] = bool(detail.get("flatten_pending"))
        state["halt_reason"] = detail.get("halt_reason")
        sync_halt_lifecycle(state)
        state["_prior_halted"] = bool(state.get("halted") or state.get("flatten_pending"))
        return state

    def save(self, trade_date: str, state: dict[str, Any], marks: dict[str, float]) -> dict[str, Any]:
        market_value = 0.0
        positions_out = {}
        for symbol, item in state["positions"].items():
            qty = int(item["qty"])
            if qty <= 0:
                continue
            px = float(marks.get(symbol, item["cost"]))
            market_value += qty * px
            positions_out[symbol] = {"qty": qty, "cost": float(item["cost"]), "market_price": px}
        cash = round(float(state["cash"]), 4)
        total = round(cash + market_value, 4)
        peak = max(float(state.get("peak_asset", state.get("initial_cash", 0))), total)
        # Prefer durable prior-halt from load(); fall back for callers that skip load.
        if "_prior_halted" in state:
            already_halted = bool(state.get("_prior_halted"))
        else:
            already_halted = bool(state.get("halted") or state.get("flatten_pending"))
        was_halted = bool(state.get("halted") or state.get("flatten_pending"))
        cfg = paper_account_config(self.settings)
        strategy_stop = -abs(float(cfg["strategy_drawdown_stop"]))
        book_dd = total / peak - 1.0 if peak > 0 else 0.0
        if was_halted or book_dd <= strategy_stop:
            state["halted"] = True
            state["halt_reason"] = state.get("halt_reason") or "strategy_drawdown"
            if _open_position_qty(state) > 0:
                state["flatten_pending"] = True
        status = sync_halt_lifecycle(state)
        detail = {
            "initial_cash": state.get("initial_cash", paper_account_config(self.settings)["initial_cash"]),
            "peak_asset": peak,
            "positions": positions_out,
            "tradable": {symbol: int(qty) for symbol, qty in state.get("tradable", {}).items() if int(qty) > 0},
            "halted": bool(state.get("halted")),
            "flatten_pending": bool(state.get("flatten_pending")),
            "halt_reason": state.get("halt_reason"),
            "halt_status": status,
        }
        execute(
            "DELETE FROM account_snapshot WHERE account_id = ? AND trade_date = ?",
            (self.account_id, trade_date),
            settings=self.settings,
        )
        execute(
            """
            INSERT INTO account_snapshot
                (account_id, trade_date, cash, market_value, total_asset, position_detail, reconcile_diff)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.account_id,
                trade_date,
                cash,
                round(market_value, 4),
                total,
                json.dumps(detail, ensure_ascii=False),
                json.dumps(
                    {
                        "asof": trade_date,
                        "cash": cash,
                        "market_value": round(market_value, 4),
                        "total_asset": total,
                        "peak_asset": peak,
                        "initial_cash": float(detail.get("initial_cash") or 0),
                        "halted": bool(detail.get("halted")),
                        "flatten_pending": bool(detail.get("flatten_pending")),
                        "halt_status": status,
                        "halt_reason": detail.get("halt_reason"),
                    },
                    ensure_ascii=False,
                ),
            ),
            settings=self.settings,
        )
        halt_info = maybe_drawdown_halt(
            peak=peak,
            total_asset=total,
            cash=cash,
            market_value=round(market_value, 4),
            initial_cash=float(detail.get("initial_cash") or 0),
            account_id=self.account_id,
            strategy_id=self.strategy_id,
            trade_date=trade_date,
            already_halted=already_halted,
            settings=self.settings,
        )
        if status == "flatten_pending":
            maybe_flatten_incomplete_alert(
                strategy_id=self.strategy_id,
                account_id=self.account_id,
                trade_date=trade_date,
                positions=positions_out,
                settings=self.settings,
            )
        elif status == "halted":
            close_flatten_incomplete_alerts(
                strategy_id=self.strategy_id,
                settings=self.settings,
            )
        # Subsequent saves in this process should treat halt as already notified.
        state["_prior_halted"] = bool(state.get("halted") or state.get("flatten_pending"))
        return {
            "cash": cash,
            "market_value": round(market_value, 4),
            "total_asset": total,
            "peak_asset": peak,
            "halted": bool(state.get("halted")),
            "flatten_pending": bool(state.get("flatten_pending")),
            "halt_status": status,
            "halt_info": halt_info,
        }


class PaperOrderService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = ensure_runtime_dirs(settings or get_settings())
        initialize_database(self.settings)
        self.broker = PaperBroker(self.settings)
        self.strategies = LocalStrategyService(self.settings)

    def list_orders(self, limit: int = 50, strategy_id: str | None = None) -> list[dict[str, Any]]:
        if strategy_id:
            return query_all(
                "SELECT * FROM standard_order WHERE strategy_id = ? ORDER BY created_at DESC LIMIT ?",
                (strategy_id, limit),
                settings=self.settings,
            )
        return query_all(
            "SELECT * FROM standard_order ORDER BY created_at DESC LIMIT ?",
            (limit,),
            settings=self.settings,
        )

    def build_orders(
        self,
        trade_date: str,
        strategy_id: str,
        *,
        signal_date: str | None = None,
        apply_fills: bool = True,
    ) -> list[dict[str, Any]]:
        if strategy_id not in STRATEGY_SPECS:
            raise ValueError(f"unknown strategy: {strategy_id}")
        gate = quality_gate(self.settings)
        if not gate["trade_allowed"]:
            return self._reject_stub(trade_date, strategy_id, "quality_block")

        dates = self._dates()
        if signal_date is None:
            signal_date = _prev_date(dates, trade_date)
        if signal_date is None:
            raise ValueError("no prior session for T+1 fill")
        if not self._calendar_open(trade_date):
            return self._reject_stub(trade_date, strategy_id, "calendar_closed")

        rows = read_market_daily(end=trade_date, settings=self.settings)
        by_key = {(str(row["trade_date"]), str(row["symbol"])): row for row in rows}
        if self._stale_blocks_trading(trade_date, rows):
            return self._reject_stub(trade_date, strategy_id, "stale_data")

        ledger = PaperLedger(strategy_id, self.settings)
        state = ledger.load(before=trade_date)
        # T+1: yesterday's buys become tradable at next session open.
        state["tradable"] = {symbol: int(item["qty"]) for symbol, item in state["positions"].items()}
        global_kill = kill_engaged(self.settings)
        sync_halt_lifecycle(state)
        book_halted = bool(state.get("halted") or state.get("flatten_pending"))
        flatten_only = global_kill or book_halted
        halt_tag = "kill_switch" if global_kill else ("strategy_halt" if book_halted else "paper")

        created: list[dict[str, Any]] = []

        if flatten_only:
            if global_kill:
                state["halted"] = True
                state["halt_reason"] = state.get("halt_reason") or "kill_switch"
                if _open_position_qty(state) > 0:
                    state["flatten_pending"] = True
            created.extend(
                self._flatten_all(
                    state=state,
                    trade_date=trade_date,
                    strategy_id=strategy_id,
                    by_key=by_key,
                    risk_tag=halt_tag,
                    apply_fills=apply_fills,
                )
            )
            if apply_fills:
                sync_halt_lifecycle(state)
                marks = {
                    symbol: float(by_key[(trade_date, symbol)]["close"])
                    for symbol in state["positions"]
                    if (trade_date, symbol) in by_key
                }
                ledger.save(trade_date, state, marks)
            return created

        try:
            self.strategies.generate_target_positions(strategy_id, signal_date)
        except PermissionError:
            return self._reject_stub(trade_date, strategy_id, "not_paper")
        targets = query_all(
            "SELECT * FROM target_position WHERE strategy_id = ? AND trade_date = ?",
            (strategy_id, signal_date),
            settings=self.settings,
        )
        nav = _nav(state, by_key, signal_date)
        intended = {row["symbol"]: float(row["target_weight"]) for row in targets}
        intended = self._apply_stops(intended, state, by_key, signal_date)

        for symbol, weight in intended.items():
            bar_signal = by_key.get((signal_date, symbol))
            bar_fill = by_key.get((trade_date, symbol))
            if not bar_signal or not bar_fill:
                continue
            px = float(bar_signal["close"])
            if px <= 0:
                continue
            target_qty = _lot(weight * nav / px)
            current = int(state["positions"].get(symbol, {}).get("qty", 0))
            delta = target_qty - current
            if delta == 0:
                continue
            side = "BUY" if delta > 0 else "SELL"
            qty = abs(delta)
            if side == "SELL":
                qty = min(qty, int(state["tradable"].get(symbol, 0)))
                qty = _lot(qty)
            if qty <= 0:
                continue
            order = self._place(
                trade_date=trade_date,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=qty,
                bar_fill=bar_fill,
                weight=weight,
                nav=nav,
                state=state,
            )
            created.append(order)
            if apply_fills:
                self._match(order, state, bar_fill, trade_date)
        leftover_sells = self._flatten_missing(intended, state, trade_date, strategy_id, by_key)
        created.extend(leftover_sells)
        if apply_fills:
            for order in leftover_sells:
                bar_fill = by_key.get((trade_date, order["symbol"]))
                if bar_fill:
                    self._match(order, state, bar_fill, trade_date)

            # Same-day flatten if this session's MTM already breaches strategy stop.
            cfg = paper_account_config(self.settings)
            strategy_stop = -abs(float(cfg["strategy_drawdown_stop"]))
            marks = {
                symbol: float(by_key[(trade_date, symbol)]["close"])
                for symbol in state["positions"]
                if (trade_date, symbol) in by_key
            }
            market_value = sum(
                int(item["qty"]) * float(marks.get(symbol, item["cost"]))
                for symbol, item in state["positions"].items()
                if int(item["qty"]) > 0
            )
            total = float(state["cash"]) + market_value
            peak = max(float(state.get("peak_asset", state.get("initial_cash", 0))), total)
            if peak > 0 and total / peak - 1.0 <= strategy_stop:
                state["halted"] = True
                state["flatten_pending"] = True
                state["halt_reason"] = "strategy_drawdown"
                if state["positions"]:
                    extra = self._flatten_all(
                        state=state,
                        trade_date=trade_date,
                        strategy_id=strategy_id,
                        by_key=by_key,
                        risk_tag="strategy_halt",
                        apply_fills=True,
                    )
                    created.extend(extra)
                sync_halt_lifecycle(state)
                marks = {
                    symbol: float(by_key[(trade_date, symbol)]["close"])
                    for symbol in state["positions"]
                    if (trade_date, symbol) in by_key
                }
            ledger.save(trade_date, state, marks)
        return created

    def _flatten_all(
        self,
        *,
        state: dict[str, Any],
        trade_date: str,
        strategy_id: str,
        by_key: dict[tuple[str, str], dict[str, Any]],
        risk_tag: str,
        apply_fills: bool,
    ) -> list[dict[str, Any]]:
        """Sell every tradable lot; never buy. Fees apply through normal fill path.

        Uses a dedicated idempotency key so halt retries are not blocked by earlier
        rejected rebalance sells on the same day (e.g. limit-down).
        """
        created: list[dict[str, Any]] = []
        for symbol, item in list(state["positions"].items()):
            qty = _lot(min(int(item["qty"]), int(state["tradable"].get(symbol, 0))))
            bar_fill = by_key.get((trade_date, symbol))
            if qty <= 0 or not bar_fill:
                continue
            order = self._place(
                trade_date=trade_date,
                strategy_id=strategy_id,
                symbol=symbol,
                side="SELL",
                quantity=qty,
                bar_fill=bar_fill,
                weight=0.0,
                nav=_nav(state, by_key, trade_date),
                state=state,
                risk_tag=risk_tag,
                idem_suffix="flatten",
            )
            created.append(order)
            if apply_fills:
                self._match(order, state, bar_fill, trade_date)
                refreshed = query_all(
                    "SELECT * FROM standard_order WHERE order_id = ?",
                    (order["order_id"],),
                    settings=self.settings,
                )
                if refreshed:
                    created[-1] = refreshed[0]
        sync_halt_lifecycle(state)
        if not created:
            created.extend(self._reject_stub(trade_date, strategy_id, risk_tag))
        return created

    def _flatten_missing(
        self,
        intended: dict[str, float],
        state: dict[str, Any],
        trade_date: str,
        strategy_id: str,
        by_key: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        extra: list[dict[str, Any]] = []
        for symbol, item in list(state["positions"].items()):
            if symbol in intended:
                continue
            qty = _lot(min(int(item["qty"]), int(state["tradable"].get(symbol, 0))))
            bar_fill = by_key.get((trade_date, symbol))
            if qty <= 0 or not bar_fill:
                continue
            extra.append(
                self._place(
                    trade_date=trade_date,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side="SELL",
                    quantity=qty,
                    bar_fill=bar_fill,
                    weight=0.0,
                    nav=_nav(state, by_key, trade_date),
                    state=state,
                )
            )
        return extra

    def _place(
        self,
        *,
        trade_date: str,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: int,
        bar_fill: dict[str, Any],
        weight: float,
        nav: float,
        state: dict[str, Any],
        risk_tag: str | None = None,
        idem_suffix: str | None = None,
    ) -> dict[str, Any]:
        idem_key = f"{strategy_id}|{trade_date}|{symbol}|{side}"
        if idem_suffix:
            idem_key = f"{idem_key}|{idem_suffix}"
        existing = query_all(
            "SELECT * FROM standard_order WHERE idem_key = ?",
            (idem_key,),
            settings=self.settings,
        )
        if existing:
            return existing[0]

        tags: list[str] = []
        if risk_tag and risk_tag not in {"paper", ""}:
            tags.append(risk_tag)
        status = "risk_pending"
        limit_row = self._limit(symbol, trade_date)
        open_px = float(bar_fill["open"])
        if limit_row and int(limit_row.get("is_suspended") or 0) == 1:
            status, tags = "rejected", ["suspended"]
        elif side == "BUY" and limit_row and _at_limit(open_px, limit_row.get("limit_up")):
            status, tags = "rejected", ["limit_up"]
        elif side == "SELL" and limit_row and _at_limit(open_px, limit_row.get("limit_down")):
            status, tags = "rejected", ["limit_down"]
        elif quantity % LOT != 0:
            status, tags = "rejected", ["lot_size"]
        elif side == "BUY":
            kind = infer_instrument_type(symbol)
            cap = MAX_WEIGHT[kind]
            notional = quantity * _fill_price(open_px, "BUY")
            if weight > cap + 1e-9 or (nav and notional / nav > cap + 1e-9):
                status, tags = "rejected", ["name_cap"]
            projected = _projected_gross(state, symbol, quantity, _fill_price(open_px, "BUY"), nav)
            if projected > GROSS_LIMIT + 1e-9:
                status, tags = "rejected", ["gross_limit"]
            fee = _fees(
                symbol,
                "BUY",
                notional,
                commission_rate=paper_account_config(self.settings)["commission_rate"],
            )
            if state["cash"] < notional + fee:
                status, tags = "rejected", ["cash"]

        now = _now()
        order_id = str(uuid4())
        tag_text = ",".join(tags) if tags else "paper"
        execute(
            """
            INSERT INTO standard_order
                (order_id, idem_key, trade_date, strategy_id, symbol, side, quantity,
                 price_type, limit_price, valid_date, risk_tags, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'limit', ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                idem_key,
                trade_date,
                strategy_id,
                symbol,
                side,
                quantity,
                open_px,
                trade_date,
                tag_text,
                status,
                now,
                now,
            ),
            settings=self.settings,
        )
        return query_all(
            "SELECT * FROM standard_order WHERE order_id = ?",
            (order_id,),
            settings=self.settings,
        )[0]

    def _match(self, order: dict[str, Any], state: dict[str, Any], bar: dict[str, Any], trade_date: str) -> None:
        if order["status"] == "rejected":
            return
        if order["status"] == "filled":
            rows = query_all(
                "SELECT * FROM execution_fill WHERE order_id = ? ORDER BY trade_time LIMIT 1",
                (order["order_id"],),
                settings=self.settings,
            )
            if rows:
                self._apply_fill_to_state(state, rows[0])
            return
        submitted = self.broker.submit(order)
        price = _fill_price(float(bar["open"]), submitted["side"])
        fill = self.broker.fill(submitted, price=price, trade_time=f"{trade_date}T09:30:00+08:00")
        self._apply_fill_to_state(
            state,
            {
                "symbol": submitted["symbol"],
                "side": submitted["side"],
                "filled_qty": fill["filled_qty"],
                "filled_price": fill["filled_price"],
                "fee": fill["fee"],
            },
        )

    def _apply_fill_to_state(self, state: dict[str, Any], fill: dict[str, Any]) -> None:
        qty = int(fill["filled_qty"])
        fee = float(fill["fee"] or 0)
        price = float(fill["filled_price"])
        symbol = str(fill["symbol"])
        pos = state["positions"].setdefault(symbol, {"qty": 0, "cost": 0.0})
        if str(fill["side"]) == "BUY":
            new_qty = pos["qty"] + qty
            pos["cost"] = (pos["cost"] * pos["qty"] + price * qty) / new_qty if new_qty else price
            pos["qty"] = new_qty
            state["cash"] -= qty * price + fee
            return
        pos["qty"] = max(0, pos["qty"] - qty)
        if pos["qty"] == 0:
            state["positions"].pop(symbol, None)
            state["tradable"].pop(symbol, None)
        else:
            state["tradable"][symbol] = max(0, int(state["tradable"].get(symbol, 0)) - qty)
        state["cash"] += qty * price - fee

    def _apply_stops(
        self,
        intended: dict[str, float],
        state: dict[str, Any],
        by_key: dict[tuple[str, str], dict[str, Any]],
        asof: str,
    ) -> dict[str, float]:
        out = dict(intended)
        for symbol, item in state["positions"].items():
            bar = by_key.get((asof, symbol))
            cost = float(item.get("cost") or 0)
            if not bar or cost <= 0:
                continue
            pnl = float(bar["close"]) / cost - 1.0
            if pnl >= TAKE_PROFIT or pnl <= STOP_LOSS:
                out[symbol] = 0.0
        return out

    def _reject_stub(self, trade_date: str, strategy_id: str, reason: str) -> list[dict[str, Any]]:
        idem_key = f"{strategy_id}|{trade_date}|GATE|{reason}"
        existing = query_all(
            "SELECT * FROM standard_order WHERE idem_key = ?",
            (idem_key,),
            settings=self.settings,
        )
        if existing:
            return existing
        now = _now()
        order_id = str(uuid4())
        execute(
            """
            INSERT INTO standard_order
                (order_id, idem_key, trade_date, strategy_id, symbol, side, quantity,
                 price_type, limit_price, valid_date, risk_tags, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, '000000.SZ', 'BUY', 0, 'limit', NULL, ?, ?, 'rejected', ?, ?)
            """,
            (order_id, idem_key, trade_date, strategy_id, trade_date, reason, now, now),
            settings=self.settings,
        )
        return query_all(
            "SELECT * FROM standard_order WHERE order_id = ?",
            (order_id,),
            settings=self.settings,
        )

    def _limit(self, symbol: str, trade_date: str) -> dict[str, Any] | None:
        rows = query_all(
            "SELECT * FROM limit_suspension WHERE symbol = ? AND trade_date = ?",
            (symbol, trade_date),
            settings=self.settings,
        )
        return rows[0] if rows else None

    def _calendar_open(self, trade_date: str) -> bool:
        rows = query_all(
            "SELECT is_open FROM trade_calendar WHERE trade_date = ? AND market = 'CN'",
            (trade_date,),
            settings=self.settings,
        )
        if not rows:
            return True
        return int(rows[0]["is_open"] or 0) == 1

    def _stale_blocks_trading(self, trade_date: str, rows: list[dict[str, Any]]) -> bool:
        """When ASQT_STALE_SEVERITY=block, refuse fills if market lags asof too far."""
        from asqt.stale import evaluate_market_staleness, stale_severity

        if stale_severity() != "block":
            return False
        calendar = query_all(
            "SELECT * FROM trade_calendar WHERE market = 'CN' AND trade_date <= ?",
            (trade_date,),
            settings=self.settings,
        )
        report = evaluate_market_staleness(
            records=rows,
            calendar=calendar,
            asof=trade_date,
        )
        return report.blocked

    def _dates(self) -> list[str]:
        rows = read_market_daily(settings=self.settings)
        return sorted({str(row["trade_date"]) for row in rows})


def max_paper_run_days(settings: Settings | None = None) -> int:
    """Largest N for paper-run: need N+1 calendar sessions (signal day + fill days)."""
    settings = ensure_runtime_dirs(settings or get_settings())
    dates = sorted({str(row["trade_date"]) for row in read_market_daily(settings=settings)})
    return max(0, len(dates) - 1)


def run_paper_days(
    *,
    strategy_id: str = "all",
    strategy_ids: list[str] | None = None,
    days: int = 20,
    settings: Settings | None = None,
    progress: Any | None = None,
    record_task: bool = True,
    mode: str = "sequential",
) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    job_key, _ids = normalize_paper_targets(strategy_id, strategy_ids)
    run_mode = normalize_paper_mode(mode)
    with paper_exclusive(settings, holder=f"paper-run:{job_key}"):
        return _run_paper_days_locked(
            strategy_id=job_key,
            days=days,
            settings=settings,
            progress=progress,
            record_task=record_task,
            mode=run_mode,
        )


def normalize_paper_mode(mode: str | None) -> str:
    value = str(mode or "sequential").strip().lower()
    if value in {"", "sequential", "normal", "serial"}:
        return "sequential"
    if value == "parallel":
        return "parallel"
    raise ValueError(f"unknown paper run mode: {mode}")


def _run_paper_days_locked(
    *,
    strategy_id: str,
    days: int,
    settings: Settings,
    progress: Any | None = None,
    record_task: bool = True,
    mode: str = "sequential",
) -> dict[str, Any]:
    job_key, requested = normalize_paper_targets(strategy_id)
    rows = read_market_daily(settings=settings)
    dates = sorted({str(row["trade_date"]) for row in rows})
    max_days = max(0, len(dates) - 1)
    if days > max_days:
        raise ValueError(
            f"模拟天数不能超过当前可用交易日上限 {max_days}（行情共 {len(dates)} 个交易日）。"
        )
    if len(dates) < days + 1:
        raise ValueError(f"need {days + 1} sessions, have {len(dates)}")
    from asqt.ops import paper_trading_enabled

    if not paper_trading_enabled(settings):
        raise ValueError("模拟交易开关为关。请先到设置页打开「模拟交易」。")
    versions = LocalStrategyService(settings)
    if job_key == "all":
        ids = []
        for sid in STRATEGY_SPECS:
            current = versions.current_version(sid)
            if current and current.get("status") == "paper":
                ids.append(sid)
        if not ids:
            raise ValueError("没有已准入模拟的策略。请先到策略页提交「准入模拟」。")
    else:
        ids = list(requested)
        for sid in ids:
            current = versions.current_version(sid)
            status = current["status"] if current else "missing"
            if status != "paper":
                raise ValueError(
                    f"策略尚未准入模拟（{sid}={status}）。请先到策略页提交「准入模拟」。"
                )
    window = dates[-(days + 1) :]
    started = _now()
    run_mode = normalize_paper_mode(mode)
    if run_mode == "parallel":
        reports = _run_paper_days_parallel(
            ids=ids,
            window=window,
            settings=settings,
            progress=progress,
            job_key=job_key,
        )
    else:
        reports = _run_paper_days_sequential(
            ids=ids,
            window=window,
            settings=settings,
            progress=progress,
            job_key=job_key,
        )
    portfolio_cash = float(paper_account_config(settings)["initial_cash"])
    # Funding universe = strategies in this run (not all admitted).
    universe = list(ids)
    cash_map = portfolio_book_cash_map(settings, universe=universe)
    book_cash = [float(cash_map[sid]) for sid in ids]
    funded: list[float] = []
    for item in reports:
        last = item.get("last")
        if last and last.get("position_detail"):
            try:
                detail = json.loads(last["position_detail"] or "{}")
                funded.append(float(detail.get("initial_cash") or 0))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        elif int(item.get("snapshots") or 0) > 0:
            funded.append(float((item.get("state") or {}).get("initial_cash") or 0))
    detail_extra = ""
    if funded:
        expected_funded = book_cash[: len(funded)]
        if len(funded) == len(ids) and any(
            abs(got - want) > 0.02 for got, want in zip(funded, expected_funded)
        ):
            detail_extra = (
                f"；本金校验异常：账本 {[round(x, 2) for x in funded]}"
                f" ≠ 份额 {[round(x, 2) for x in expected_funded]}"
                f"（组合 {portfolio_cash:.2f} / {len(universe)}）"
            )
    ok = all(item.get("incomplete_reason") is None for item in reports)
    reasons = sorted({item["incomplete_reason"] for item in reports if item.get("incomplete_reason")})
    detail = _paper_run_detail(ok=ok, reasons=reasons, reports=reports, days=days) + detail_extra
    summary = {
        "ok": ok,
        "days": days,
        "mode": run_mode,
        "window": {"start": window[0], "end": window[-1]},
        "reports": reports,
        "incomplete_reasons": reasons,
        "detail": detail,
        "portfolio_cash": portfolio_cash,
        "book_cash": book_cash,
        "funding_universe": universe,
    }
    if record_task:
        execute(
            """
            INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
            VALUES (?, 'paper-run', ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                "success" if summary["ok"] else "partial" if reasons else "failed",
                started,
                _now(),
                json.dumps(
                    {
                        "days": days,
                        "mode": run_mode,
                        "window": summary["window"],
                        "incomplete_reasons": reasons,
                        "detail": detail,
                    },
                    ensure_ascii=False,
                ),
            ),
            settings=settings,
        )
    return summary


def _skipped_kill_report(
    *,
    sid: str,
    wanted: int,
    window: list[str],
    settings: Settings,
) -> dict[str, Any]:
    ledger = PaperLedger(sid, settings)
    last = query_all(
        "SELECT * FROM account_snapshot WHERE account_id = ? ORDER BY trade_date",
        (account_id_for(sid),),
        settings=settings,
    )
    return {
        "strategy_id": sid,
        "sessions": wanted,
        "orders": 0,
        "fills": 0,
        "snapshots": 0,
        "snapshots_total": len(last),
        "last": last[-1] if last else None,
        "state": ledger.load(),
        "incomplete_reason": "kill_switch",
        "skipped": True,
    }


def _orders_triggered_kill(created: list[dict[str, Any]], settings: Settings) -> bool:
    del created  # liquidation tags must not stop sibling books
    return kill_engaged(settings)


def _strategy_window_report(
    *,
    sid: str,
    window: list[str],
    settings: Settings,
    orders: int,
    halt_reason: str | None,
) -> dict[str, Any]:
    wanted = len(window) - 1
    ledger = PaperLedger(sid, settings)
    last = query_all(
        "SELECT * FROM account_snapshot WHERE account_id = ? ORDER BY trade_date",
        (account_id_for(sid),),
        settings=settings,
    )
    in_window = [row for row in last if window[0] < str(row["trade_date"]) <= window[-1]]
    incomplete = None
    if halt_reason == "kill_switch" or kill_engaged(settings):
        incomplete = "kill_switch"
    elif len(in_window) < wanted:
        incomplete = "short_snapshots"
    return {
        "strategy_id": sid,
        "sessions": wanted,
        "orders": orders,
        "fills": query_all(
            """
            SELECT COUNT(*) AS c FROM execution_fill f
            JOIN standard_order o ON o.order_id = f.order_id
            WHERE o.strategy_id = ?
            """,
            (sid,),
            settings=settings,
        )[0]["c"],
        "snapshots": len(in_window),
        "snapshots_total": len(last),
        "last": last[-1] if last else None,
        "state": ledger.load(),
        "incomplete_reason": incomplete,
    }


def _run_one_strategy_window(
    *,
    sid: str,
    window: list[str],
    settings: Settings,
    on_step: Any | None = None,
) -> dict[str, Any]:
    """Run one strategy across the window. Caller must already hold paper_exclusive."""
    wanted = len(window) - 1
    if kill_engaged(settings) and not query_all(
        "SELECT 1 AS ok FROM account_snapshot WHERE account_id = ? LIMIT 1",
        (account_id_for(sid),),
        settings=settings,
    ):
        # Fresh book + pre-engaged global kill: skip empty run.
        return _skipped_kill_report(sid=sid, wanted=wanted, window=window, settings=settings)
    service = PaperOrderService(settings)
    orders = 0
    saw_kill = kill_engaged(settings)
    for index, signal_date in enumerate(window[:-1]):
        fill_date = window[index + 1]
        if kill_engaged(settings):
            saw_kill = True
        created = service.build_orders(fill_date, sid, signal_date=signal_date, apply_fills=True)
        if kill_engaged(settings):
            saw_kill = True
        orders += len(created)
        if on_step:
            on_step(1, f"{sid} {fill_date}")
    return _strategy_window_report(
        sid=sid,
        window=window,
        settings=settings,
        orders=orders,
        halt_reason="kill_switch" if saw_kill or kill_engaged(settings) else None,
    )


def _run_paper_days_sequential(
    *,
    ids: list[str],
    window: list[str],
    settings: Settings,
    progress: Any | None = None,
    job_key: str,
) -> list[dict[str, Any]]:
    wanted = len(window) - 1
    grand = wanted * len(ids)
    done = 0
    reports: list[dict[str, Any]] = []
    _prepare_shared_book_cash(
        ids=ids,
        job_key=job_key,
        settings=settings,
        reason="multi-strategy sequential paper run reset",
    )
    try:
        for sid in ids:
            if kill_engaged(settings):
                done += wanted
                if progress:
                    progress(done, grand, f"{sid} skipped_kill")
                reports.append(_skipped_kill_report(sid=sid, wanted=wanted, window=window, settings=settings))
                continue

            def on_step(delta: int, label: str, *, _sid: str = sid) -> None:
                nonlocal done
                done += delta
                if progress and (done == 1 or done == grand or done % 5 == 0 or "halt" in label):
                    progress(done, grand, label)

            reports.append(
                _run_one_strategy_window(sid=sid, window=window, settings=settings, on_step=on_step)
            )
    finally:
        _clear_cash_overrides(settings, ids)
    return reports


def _run_paper_days_parallel(
    *,
    ids: list[str],
    window: list[str],
    settings: Settings,
    progress: Any | None = None,
    job_key: str,
) -> list[dict[str, Any]]:
    """Reset selected books, split cash, run strategies day-aligned in parallel.

    Outer loop is the shared trading calendar; each session fans out to workers.
    Portfolio kill liquidates every book but keeps day alignment (cash-only days).
    Strategy-level halt only flattens that book; siblings keep trading.

    Caller must already hold paper_exclusive; workers must not nest exclusive.
    """
    _prepare_shared_book_cash(
        ids=ids,
        job_key=job_key,
        settings=settings,
        reason="parallel paper run reset",
    )
    wanted = len(window) - 1
    grand = wanted * len(ids)
    done = 0
    order_counts = {sid: 0 for sid in ids}
    saw_kill = kill_engaged(settings)

    def bump(delta: int, label: str) -> None:
        nonlocal done
        done += delta
        if progress and (done == 1 or done == grand or done % 5 == 0 or "halt" in label):
            progress(done, grand, label)

    def run_day(sid: str, fill_date: str, signal_date: str) -> tuple[str, list[dict[str, Any]]]:
        created = PaperOrderService(settings).build_orders(
            fill_date,
            sid,
            signal_date=signal_date,
            apply_fills=True,
        )
        return sid, created

    try:
        if saw_kill:
            bump(grand, "parallel skipped_kill")
            return [
                _skipped_kill_report(sid=sid, wanted=wanted, window=window, settings=settings)
                for sid in ids
            ]

        workers = max(1, len(ids))
        for index, signal_date in enumerate(window[:-1]):
            fill_date = window[index + 1]
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="asqt-paper-par") as pool:
                day_results = list(
                    pool.map(
                        lambda sid, _fd=fill_date, _sd=signal_date: run_day(sid, _fd, _sd),
                        ids,
                    )
                )
            for sid, created in day_results:
                order_counts[sid] += len(created)
            if kill_engaged(settings):
                saw_kill = True
            bump(len(ids), f"parallel {fill_date}")
    finally:
        _clear_cash_overrides(settings, ids)

    halt_reason = "kill_switch" if saw_kill or kill_engaged(settings) else None
    return [
        _strategy_window_report(
            sid=sid,
            window=window,
            settings=settings,
            orders=order_counts[sid],
            halt_reason=halt_reason,
        )
        for sid in ids
    ]


def _paper_run_detail(
    *,
    ok: bool,
    reasons: list[str],
    reports: list[dict[str, Any]],
    days: int,
) -> str:
    if ok:
        return f"模拟已跑完（{days} 个交易日）"
    parts = []
    for item in reports:
        sid = item["strategy_id"]
        reason = item.get("incomplete_reason")
        if reason == "kill_switch":
            if int(item.get("snapshots") or 0) == 0:
                parts.append(f"{sid} 0/{item['sessions']} 日：急停已开，整段被跳过（无快照）")
            else:
                parts.append(
                    f"{sid} 仅完成 {item['snapshots']}/{item['sessions']} 日：急停打开后不再写快照"
                )
        elif reason == "short_snapshots":
            parts.append(f"{sid} 仅完成 {item['snapshots']}/{item['sessions']} 日快照")
    if not parts and "kill_switch" in reasons:
        return "模拟未完整：急停已打开，后续交易日被拒绝"
    return "；".join(parts) if parts else "模拟未完整"


def advance_paper_session(
    *,
    fill_date: str | None = None,
    trigger: str = "manual",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run one T+1 session if the as-of date has no snapshot yet. Idempotent."""
    from asqt.ops import paper_trading_enabled

    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    started = _now()
    if paper_run_locked(settings):
        return _paper_daily_result(
            status="skipped",
            reason="paper_busy",
            trigger=trigger,
            started=started,
            settings=settings,
        )
    dates = sorted({str(row["trade_date"]) for row in read_market_daily(settings=settings)})
    if len(dates) < 2:
        return _paper_daily_result(
            status="skipped",
            reason="need_two_sessions",
            trigger=trigger,
            started=started,
            settings=settings,
        )
    asof = fill_date or dates[-1]
    if asof not in dates:
        return _paper_daily_result(
            status="skipped",
            reason="unknown_fill_date",
            trigger=trigger,
            fill_date=asof,
            started=started,
            settings=settings,
        )
    index = dates.index(asof)
    if index < 1:
        return _paper_daily_result(
            status="skipped",
            reason="no_signal_date",
            trigger=trigger,
            fill_date=asof,
            started=started,
            settings=settings,
        )
    signal_date = dates[index - 1]
    if not paper_trading_enabled(settings):
        return _paper_daily_result(
            status="skipped",
            reason="paper_trading_off",
            trigger=trigger,
            fill_date=asof,
            signal_date=signal_date,
            started=started,
            settings=settings,
        )
    if kill_engaged(settings):
        return _paper_daily_result(
            status="skipped",
            reason="kill_switch",
            trigger=trigger,
            fill_date=asof,
            signal_date=signal_date,
            started=started,
            settings=settings,
        )
    gate = quality_gate(settings)
    if not gate["trade_allowed"]:
        return _paper_daily_result(
            status="skipped",
            reason="quality_block",
            trigger=trigger,
            fill_date=asof,
            signal_date=signal_date,
            started=started,
            settings=settings,
        )
    versions = LocalStrategyService(settings)
    admitted = []
    for sid in STRATEGY_SPECS:
        current = versions.current_version(sid)
        if current and current.get("status") == "paper":
            admitted.append(sid)
    if not admitted:
        return _paper_daily_result(
            status="skipped",
            reason="no_paper_strategy",
            trigger=trigger,
            fill_date=asof,
            signal_date=signal_date,
            started=started,
            settings=settings,
        )
    already: list[str] = []
    ran: list[str] = []
    service = PaperOrderService(settings)
    for sid in admitted:
        snaps = query_all(
            "SELECT trade_date FROM account_snapshot WHERE account_id = ? AND trade_date = ?",
            (account_id_for(sid), asof),
            settings=settings,
        )
        if snaps:
            already.append(sid)
            continue
        service.build_orders(asof, sid, signal_date=signal_date, apply_fills=True)
        ran.append(sid)
    status = "success" if ran else "skipped"
    reason = "advanced" if ran else "already_current"
    return _paper_daily_result(
        status=status,
        reason=reason,
        trigger=trigger,
        fill_date=asof,
        signal_date=signal_date,
        ran=ran,
        already=already,
        started=started,
        settings=settings,
        ok=bool(ran) or bool(already),
    )


def after_market_ready(
    *,
    asof: str | None,
    trigger: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Called after a successful/skipped daily sync. Failures must not fail the sync job."""
    from asqt.ops import LocalAlertService

    if not asof:
        return None
    try:
        return advance_paper_session(fill_date=asof, trigger=f"sync:{trigger}", settings=settings)
    except Exception as exc:
        LocalAlertService(settings).raise_alert(
            "high",
            "paper_daily",
            "日终模拟失败",
            str(exc)[:500],
        )
        return {"ok": False, "status": "failed", "reason": str(exc)[:500], "fill_date": asof}


def _paper_daily_result(
    *,
    status: str,
    reason: str,
    trigger: str,
    started: str,
    settings: Settings,
    fill_date: str | None = None,
    signal_date: str | None = None,
    ran: list[str] | None = None,
    already: list[str] | None = None,
    ok: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": True if ok is None else ok,
        "status": status,
        "reason": reason,
        "trigger": trigger,
        "fill_date": fill_date,
        "signal_date": signal_date,
        "ran": ran or [],
        "already": already or [],
    }
    if status == "skipped" and reason not in {"already_current"}:
        payload["ok"] = True
    execute(
        """
        INSERT INTO task_run (run_id, task_name, status, started_at, finished_at, message)
        VALUES (?, 'paper-daily', ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            status,
            started,
            _now(),
            json.dumps(payload, ensure_ascii=False),
        ),
        settings=settings,
    )
    return payload


def paper_curve(strategy_id: str, settings: Settings | None = None) -> list[dict[str, Any]]:
    return query_all(
        "SELECT trade_date, cash, market_value, total_asset FROM account_snapshot WHERE account_id = ? ORDER BY trade_date",
        (account_id_for(strategy_id),),
        settings=settings,
    )


def resolve_paper_strategy(strategy_id: str | None) -> str:
    if not strategy_id or strategy_id == "all":
        return "stock_momentum_topk"
    if "," in str(strategy_id):
        return str(strategy_id).split(",")[0].strip() or "stock_momentum_topk"
    return strategy_id


def paper_strategy_ids(strategy_id: str | None) -> list[str]:
    key, ids = normalize_paper_targets(strategy_id or "all")
    if key == "all":
        return list(STRATEGY_SPECS)
    return ids


def normalize_paper_targets(
    strategy_id: str = "all",
    strategy_ids: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Return (job_key, ordered ids). job_key is stored on paper-run tasks."""
    if strategy_ids is not None:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in strategy_ids:
            sid = str(raw or "").strip()
            if not sid or sid in seen:
                continue
            if sid == "all":
                return "all", list(STRATEGY_SPECS)
            if sid not in STRATEGY_SPECS:
                raise ValueError(f"unknown strategy: {sid}")
            seen.add(sid)
            ordered.append(sid)
        if not ordered:
            raise ValueError("strategy_ids must not be empty")
        if set(ordered) == set(STRATEGY_SPECS):
            return "all", list(STRATEGY_SPECS)
        return ",".join(ordered), ordered
    key = str(strategy_id or "all").strip() or "all"
    if key == "all":
        return "all", list(STRATEGY_SPECS)
    if "," in key:
        return normalize_paper_targets(strategy_ids=key.split(","))
    if key not in STRATEGY_SPECS:
        raise ValueError(f"unknown strategy: {key}")
    return key, [key]


def reset_paper_account(
    *,
    strategy_id: str = "all",
    strategy_ids: list[str] | None = None,
    actor: str = "operator",
    reason: str = "reset paper account",
    settings: Settings | None = None,
    clear_kill: bool = True,
) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    job_key, _ids = normalize_paper_targets(strategy_id, strategy_ids)
    with paper_exclusive(settings, holder=f"paper-reset:{job_key}"):
        return _reset_paper_account_locked(
            strategy_id=job_key,
            actor=actor,
            reason=reason,
            settings=settings,
            clear_kill=clear_kill,
        )


def _reset_paper_account_locked(
    *,
    strategy_id: str,
    actor: str,
    reason: str,
    settings: Settings,
    clear_kill: bool = True,
) -> dict[str, Any]:
    _key, ids = normalize_paper_targets(strategy_id)
    from asqt.db import connect

    reports: list[dict[str, Any]] = []
    with connect(settings) as conn:
        for sid in ids:
            account_id = account_id_for(sid)
            fills = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM execution_fill
                    WHERE order_id IN (SELECT order_id FROM standard_order WHERE strategy_id = ?)
                    """,
                    (sid,),
                ).fetchone()[0]
            )
            orders = int(
                conn.execute(
                    "SELECT COUNT(*) FROM standard_order WHERE strategy_id = ?",
                    (sid,),
                ).fetchone()[0]
            )
            snapshots = int(
                conn.execute(
                    "SELECT COUNT(*) FROM account_snapshot WHERE account_id = ?",
                    (account_id,),
                ).fetchone()[0]
            )
            conn.execute(
                """
                DELETE FROM execution_fill
                WHERE order_id IN (SELECT order_id FROM standard_order WHERE strategy_id = ?)
                """,
                (sid,),
            )
            conn.execute("DELETE FROM standard_order WHERE strategy_id = ?", (sid,))
            conn.execute("DELETE FROM account_snapshot WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM target_position WHERE strategy_id = ?", (sid,))
            reports.append(
                {
                    "strategy_id": sid,
                    "account_id": account_id,
                    "deleted_fills": fills,
                    "deleted_orders": orders,
                    "deleted_snapshots": snapshots,
                }
            )
        conn.execute(
            """
            INSERT INTO operation_audit
                (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                actor,
                "paper_reset",
                "account",
                ",".join(ids),
                reason,
                json.dumps({"reports": reports}, ensure_ascii=False),
                "empty",
            ),
        )
        conn.commit()
    reset_portfolio_peak(settings)
    kill_before = kill_engaged(settings)
    kill_info: dict[str, Any] = {"engaged": kill_before, "cleared": False}
    if clear_kill and kill_before:
        kill_info = set_kill_switch(
            False,
            reason or "paper reset clears kill switch",
            actor=actor,
            settings=settings,
        )
        kill_info = {
            "engaged": bool(kill_info.get("engaged")),
            "cleared": True,
            "before": kill_info.get("before"),
            "after": kill_info.get("after"),
        }
    return {
        "ok": True,
        "strategy_id": "all" if len(ids) > 1 else ids[0],
        "reports": reports,
        "kill_switch": kill_info,
    }


def clear_strategy_halt(
    strategy_id: str,
    reason: str,
    *,
    actor: str = "operator",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Clear single-strategy flatten/halt so later sessions can trade again.

    Resets the book peak to current NAV so the same drawdown does not
    immediately re-trigger halt on the next save.
    """
    if not (reason or "").strip():
        raise ValueError("clear strategy halt requires a reason")
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    sid = resolve_paper_strategy(strategy_id)
    with paper_exclusive(settings, holder=f"paper-clear-halt:{sid}"):
        return _clear_strategy_halt_locked(
            strategy_id=sid,
            reason=reason.strip(),
            actor=actor,
            settings=settings,
        )


def _clear_strategy_halt_locked(
    *,
    strategy_id: str,
    reason: str,
    actor: str,
    settings: Settings,
) -> dict[str, Any]:
    ledger = PaperLedger(strategy_id, settings)
    state = ledger.load()
    before_status = halt_status_of(state)
    rows = query_all(
        """
        SELECT trade_date, cash, market_value, total_asset, position_detail, reconcile_diff
        FROM account_snapshot
        WHERE account_id = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (ledger.account_id,),
        settings=settings,
    )
    if not rows or before_status == "active":
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "changed": False,
            "halt_status": "active",
            "before_status": before_status,
            "reason": reason,
        }
    row = rows[0]
    detail = json.loads(row["position_detail"] or "{}")
    total = float(row["total_asset"])
    peak_before = float(detail.get("peak_asset") or total)
    detail["halted"] = False
    detail["flatten_pending"] = False
    detail["halt_reason"] = None
    detail["halt_status"] = "active"
    detail["peak_asset"] = total
    detail["halt_cleared_reason"] = reason
    try:
        reconcile = json.loads(row["reconcile_diff"] or "{}")
        if not isinstance(reconcile, dict):
            reconcile = {}
    except (TypeError, json.JSONDecodeError):
        reconcile = {}
    reconcile.update(
        {
            "halted": False,
            "flatten_pending": False,
            "halt_status": "active",
            "halt_reason": None,
            "peak_asset": total,
        }
    )
    execute(
        """
        UPDATE account_snapshot
        SET position_detail = ?, reconcile_diff = ?
        WHERE account_id = ? AND trade_date = ?
        """,
        (
            json.dumps(detail, ensure_ascii=False),
            json.dumps(reconcile, ensure_ascii=False),
            ledger.account_id,
            row["trade_date"],
        ),
        settings=settings,
    )
    closed_alerts = close_strategy_halt_alerts(
        strategy_id=strategy_id,
        reason=reason,
        settings=settings,
    )
    execute(
        """
        INSERT INTO operation_audit
            (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            actor,
            "paper_clear_halt",
            "account",
            ledger.account_id,
            reason,
            json.dumps(
                {
                    "halt_status": before_status,
                    "peak_asset": peak_before,
                    "trade_date": row["trade_date"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "halt_status": "active",
                    "peak_asset": total,
                    "closed_alerts": closed_alerts,
                },
                ensure_ascii=False,
            ),
        ),
        settings=settings,
    )
    return {
        "ok": True,
        "strategy_id": strategy_id,
        "changed": True,
        "halt_status": "active",
        "before_status": before_status,
        "peak_asset": total,
        "peak_before": peak_before,
        "trade_date": row["trade_date"],
        "closed_alerts": closed_alerts,
        "reason": reason,
    }


def paper_board(strategy_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = ensure_runtime_dirs(settings or get_settings())
    initialize_database(settings)
    sid = resolve_paper_strategy(strategy_id)
    ledger = PaperLedger(sid, settings)
    state = ledger.load()
    curve = paper_curve(sid, settings)
    fills = query_all(
        """
        SELECT
            f.fill_id,
            f.trade_time,
            o.trade_date,
            o.strategy_id,
            f.symbol,
            f.side,
            f.filled_qty,
            f.filled_price,
            f.fee
        FROM execution_fill f
        JOIN standard_order o ON o.order_id = f.order_id
        WHERE o.strategy_id = ?
        ORDER BY o.trade_date, f.trade_time
        """,
        (sid,),
        settings=settings,
    )
    order_rows = query_all(
        """
        SELECT status, risk_tags, COUNT(*) AS c
        FROM standard_order
        WHERE strategy_id = ?
        GROUP BY status, risk_tags
        """,
        (sid,),
        settings=settings,
    )
    filled_orders = sum(int(row["c"]) for row in order_rows if row["status"] == "filled")
    rejected_orders = sum(int(row["c"]) for row in order_rows if row["status"] == "rejected")
    buy_notional = 0.0
    sell_notional = 0.0
    fees = 0.0
    by_date: dict[str, dict[str, Any]] = {}
    for fill in fills:
        qty = int(fill["filled_qty"])
        price = float(fill["filled_price"])
        fee = float(fill["fee"] or 0)
        notional = round(qty * price, 4)
        fill["notional"] = notional
        fees += fee
        if fill["side"] == "SELL":
            sell_notional += notional
        else:
            buy_notional += notional
        day = str(fill["trade_date"])
        bucket = by_date.setdefault(
            day,
            {"buys": 0, "sells": 0, "buy_notional": 0.0, "sell_notional": 0.0, "fees": 0.0},
        )
        if fill["side"] == "SELL":
            bucket["sells"] += 1
            bucket["sell_notional"] += notional
        else:
            bucket["buys"] += 1
            bucket["buy_notional"] += notional
        bucket["fees"] += fee
    raw_initial = state.get("initial_cash")
    initial = float(INITIAL_CASH if raw_initial is None else raw_initial)
    prev = initial
    peak = initial
    max_dd = 0.0
    timeline = []
    for row in curve:
        asset = float(row["total_asset"])
        cash = float(row["cash"])
        market_value = float(row["market_value"])
        daily_pnl = round(asset - prev, 4)
        daily_return = (asset / prev - 1.0) if prev else 0.0
        total_return = asset / initial - 1.0 if initial else 0.0
        peak = max(peak, asset)
        drawdown = asset / peak - 1.0 if peak else 0.0
        max_dd = min(max_dd, drawdown)
        day = str(row["trade_date"])
        flow = by_date.get(day, {})
        timeline.append(
            {
                "trade_date": day,
                "cash": cash,
                "market_value": market_value,
                "total_asset": asset,
                "daily_pnl": daily_pnl,
                "daily_return": round(daily_return, 10),
                "total_return": round(total_return, 10),
                "drawdown": round(drawdown, 10),
                "buys": int(flow.get("buys") or 0),
                "sells": int(flow.get("sells") or 0),
                "buy_notional": round(float(flow.get("buy_notional") or 0), 4),
                "sell_notional": round(float(flow.get("sell_notional") or 0), 4),
                "fees": round(float(flow.get("fees") or 0), 4),
            }
        )
        prev = asset
    last = timeline[-1] if timeline else None
    positions = []
    for symbol, item in (state.get("positions") or {}).items():
        qty = int(item.get("qty") or 0)
        if qty <= 0:
            continue
        cost = float(item.get("cost") or 0)
        mark = float(item.get("market_price") or cost)
        positions.append(
            {
                "symbol": symbol,
                "qty": qty,
                "cost": cost,
                "market_price": mark,
                "market_value": round(qty * mark, 4),
            }
        )
    positions.sort(key=lambda item: item["market_value"], reverse=True)
    end_asset = float(last["total_asset"]) if last else initial
    peak_return = round(peak / initial - 1.0, 10) if initial else 0.0
    summary = {
        "window_start": timeline[0]["trade_date"] if timeline else None,
        "window_end": timeline[-1]["trade_date"] if timeline else None,
        "sessions": len(timeline),
        "initial_cash": initial,
        "end_asset": end_asset,
        "cash": float(last["cash"]) if last else float(state.get("cash") or initial),
        "market_value": float(last["market_value"]) if last else 0.0,
        "total_return": round(end_asset / initial - 1.0, 10) if initial else 0.0,
        "max_drawdown": round(max_dd, 10),
        "peak_asset": peak,
        "peak_return": peak_return,
        "position_count": len(positions),
        "orders_filled": filled_orders,
        "orders_rejected": rejected_orders,
        "fills": len(fills),
        "buy_notional": round(buy_notional, 4),
        "sell_notional": round(sell_notional, 4),
        "fees": round(fees, 4),
        "halted": bool(state.get("halted")),
        "flatten_pending": bool(state.get("flatten_pending")),
        "halt_status": halt_status_of(state),
        "halt_reason": state.get("halt_reason"),
    }
    return {
        "account_id": account_id_for(sid),
        "strategy_id": sid,
        "state": state,
        "curve": curve,
        "fills": fills,
        "positions": positions,
        "timeline": timeline,
        "summary": summary,
        "reconcile": paper_cash_reconcile(summary=summary, fills=fills, positions=positions, state=state),
    }


def paper_cash_reconcile(
    *,
    summary: dict[str, Any],
    fills: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Replay fills into cash and share quantity; compare with the ledger snapshot."""
    tol = 0.05
    initial = float(summary.get("initial_cash") or 0)
    buy_notional = 0.0
    sell_notional = 0.0
    fees = 0.0
    buy_qty = 0
    sell_qty = 0
    replay_qty: dict[str, int] = {}
    for fill in fills:
        qty = int(fill.get("filled_qty") or 0)
        notional = float(fill.get("notional") or 0)
        fee = float(fill.get("fee") or 0)
        symbol = str(fill.get("symbol") or "")
        fees += fee
        if str(fill.get("side")) == "SELL":
            sell_notional += notional
            sell_qty += qty
            replay_qty[symbol] = int(replay_qty.get(symbol) or 0) - qty
        else:
            buy_notional += notional
            buy_qty += qty
            replay_qty[symbol] = int(replay_qty.get(symbol) or 0) + qty
    expected_cash = round(initial - buy_notional + sell_notional - fees, 4)
    actual_cash = round(float(state.get("cash") or summary.get("cash") or 0), 4)
    book_qty = {row["symbol"]: int(row["qty"]) for row in positions if int(row.get("qty") or 0) > 0}
    replay_held = {symbol: qty for symbol, qty in replay_qty.items() if qty > 0}
    qty_mismatches = []
    symbols = sorted(set(book_qty) | set(replay_held))
    for symbol in symbols:
        expected = int(replay_held.get(symbol) or 0)
        actual = int(book_qty.get(symbol) or 0)
        if expected != actual:
            qty_mismatches.append(
                {"symbol": symbol, "expected": expected, "actual": actual, "diff": actual - expected}
            )
    expected_mv = round(sum(float(row.get("market_value") or 0) for row in positions), 4)
    actual_mv = round(float(summary.get("market_value") or 0), 4)
    expected_asset = round(expected_cash + expected_mv, 4)
    actual_asset = round(float(summary.get("end_asset") or actual_cash + actual_mv), 4)

    def _row(name: str, expected: float, actual: float, *, quantity: bool = False) -> dict[str, Any]:
        diff = round(actual - expected, 4 if not quantity else 0)
        ok = abs(diff) <= (0 if quantity else tol)
        return {
            "name": name,
            "expected": expected,
            "actual": actual,
            "diff": diff,
            "ok": ok,
        }

    checks = [
        _row("现金", expected_cash, actual_cash),
        _row("买入额", round(buy_notional, 4), round(float(summary.get("buy_notional") or 0), 4)),
        _row("卖出额", round(sell_notional, 4), round(float(summary.get("sell_notional") or 0), 4)),
        _row("费用", round(fees, 4), round(float(summary.get("fees") or 0), 4)),
        _row("持仓市值", expected_mv, actual_mv),
        _row("总资产", expected_asset, actual_asset),
        _row("持仓数量合计", float(sum(replay_held.values())), float(sum(book_qty.values())), quantity=True),
    ]
    ok = all(row["ok"] for row in checks) and not qty_mismatches
    return {
        "ok": ok,
        "asof": summary.get("window_end"),
        "initial_cash": initial,
        "buy_notional": round(buy_notional, 4),
        "sell_notional": round(sell_notional, 4),
        "fees": round(fees, 4),
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "expected_cash": expected_cash,
        "actual_cash": actual_cash,
        "cash_diff": round(actual_cash - expected_cash, 4),
        "market_value": actual_mv,
        "end_asset": actual_asset,
        "peak_asset": round(float(summary.get("peak_asset") or state.get("peak_asset") or initial), 4),
        "peak_return": round(
            float(
                summary["peak_return"]
                if summary.get("peak_return") is not None
                else (
                    (float(summary.get("peak_asset") or state.get("peak_asset") or initial) / initial - 1.0)
                    if initial
                    else 0.0
                )
            ),
            10,
        ),
        "checks": checks,
        "qty_mismatches": qty_mismatches,
        "formula": "期末现金 = 本金 − 买入额 + 卖出额 − 费用；持仓数量 = 买入数量 − 卖出数量；总资产 = 现金 + 持仓市值",
    }


def _prev_date(dates: list[str], trade_date: str) -> str | None:
    prior = [day for day in dates if day < trade_date]
    return prior[-1] if prior else None


def _nav(state: dict[str, Any], by_key: dict[tuple[str, str], dict[str, Any]], asof: str) -> float:
    total = float(state["cash"])
    for symbol, item in state["positions"].items():
        bar = by_key.get((asof, symbol))
        px = float(bar["close"]) if bar else float(item["cost"])
        total += int(item["qty"]) * px
    return total


def _at_limit(price: float, bound: Any) -> bool:
    if bound is None:
        return False
    try:
        return abs(float(price) - float(bound)) <= 1e-6
    except (TypeError, ValueError):
        return False


def _projected_gross(state: dict[str, Any], symbol: str, buy_qty: int, price: float, nav: float) -> float:
    if nav <= 0:
        return 1.0
    mv = 0.0
    for name, item in state["positions"].items():
        mv += int(item["qty"]) * float(item.get("cost") or 0)
    mv += buy_qty * price
    return mv / nav
