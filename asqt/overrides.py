"""Paper target-position overrides (force_in / force_out / cap)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import execute, initialize_database, query_all

OVERRIDE_ACTIONS = frozenset({"force_in", "force_out", "cap"})


def list_overrides(
    *,
    strategy_id: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    initialize_database(settings)
    if strategy_id:
        return query_all(
            """
            SELECT * FROM paper_override
            WHERE strategy_id = ?
            ORDER BY symbol
            """,
            (strategy_id.strip(),),
            settings=settings,
        )
    return query_all(
        "SELECT * FROM paper_override ORDER BY strategy_id, symbol",
        settings=settings,
    )


def upsert_override(
    *,
    strategy_id: str,
    symbol: str,
    action: str,
    weight: float | None = None,
    reason: str | None = None,
    actor: str = "operator",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    sid = (strategy_id or "").strip()
    sym = (symbol or "").strip()
    act = (action or "").strip().lower()
    if not sid or not sym:
        raise ValueError("strategy_id and symbol are required")
    if act not in OVERRIDE_ACTIONS:
        raise ValueError(f"action must be one of {sorted(OVERRIDE_ACTIONS)}")
    if act in {"force_in", "cap"} and weight is None:
        raise ValueError(f"{act} requires weight")
    if act == "force_out":
        weight = None
    if weight is not None:
        weight = float(weight)
        if weight < 0:
            raise ValueError("weight must be >= 0")
        if act == "force_in" and weight <= 0:
            raise ValueError("force_in weight must be > 0")
        if act == "cap" and weight <= 0:
            raise ValueError("cap weight must be > 0")

    before_rows = query_all(
        "SELECT * FROM paper_override WHERE strategy_id = ? AND symbol = ?",
        (sid, sym),
        settings=settings,
    )
    before = dict(before_rows[0]) if before_rows else None
    reason_text = (reason or "").strip() or None
    execute(
        """
        INSERT INTO paper_override
            (strategy_id, symbol, action, weight, reason, actor, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(strategy_id, symbol) DO UPDATE SET
            action = excluded.action,
            weight = excluded.weight,
            reason = excluded.reason,
            actor = excluded.actor,
            updated_at = CURRENT_TIMESTAMP
        """,
        (sid, sym, act, weight, reason_text, actor),
        settings=settings,
    )
    after_rows = query_all(
        "SELECT * FROM paper_override WHERE strategy_id = ? AND symbol = ?",
        (sid, sym),
        settings=settings,
    )
    after = dict(after_rows[0])
    execute(
        """
        INSERT INTO operation_audit
            (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            actor,
            "upsert",
            "paper_override",
            f"{sid}:{sym}",
            reason_text or act,
            None if before is None else str(before),
            str(after),
        ),
        settings=settings,
    )
    return after


def delete_override(
    *,
    strategy_id: str,
    symbol: str,
    actor: str = "operator",
    reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    initialize_database(settings)
    sid = (strategy_id or "").strip()
    sym = (symbol or "").strip()
    if not sid or not sym:
        raise ValueError("strategy_id and symbol are required")
    before_rows = query_all(
        "SELECT * FROM paper_override WHERE strategy_id = ? AND symbol = ?",
        (sid, sym),
        settings=settings,
    )
    if not before_rows:
        raise KeyError(f"no override for {sid}:{sym}")
    before = dict(before_rows[0])
    execute(
        "DELETE FROM paper_override WHERE strategy_id = ? AND symbol = ?",
        (sid, sym),
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
            "delete",
            "paper_override",
            f"{sid}:{sym}",
            (reason or "").strip() or "delete",
            str(before),
            None,
        ),
        settings=settings,
    )
    return before


def apply_overrides(
    weights: dict[str, float],
    strategy_id: str,
    *,
    settings: Settings | None = None,
    actor: str = "system",
    audit: bool = True,
) -> tuple[dict[str, float], dict[str, str]]:
    """Apply force_in / force_out / cap; overridden symbols get reason override:*."""
    settings = settings or get_settings()
    initialize_database(settings)
    sid = (strategy_id or "").strip()
    if not sid:
        raise ValueError("strategy_id is required")

    result = {str(symbol): float(weight) for symbol, weight in weights.items() if float(weight) > 0}
    reasons: dict[str, str] = {}
    overrides = list_overrides(strategy_id=sid, settings=settings)
    if not overrides:
        return result, reasons

    before_snapshot = dict(result)
    for row in overrides:
        symbol = str(row["symbol"])
        action = str(row["action"]).strip().lower()
        raw_weight = row.get("weight")
        if action == "force_out":
            if symbol in result:
                result.pop(symbol, None)
                reasons[symbol] = "override:force_out"
        elif action == "force_in":
            w = float(raw_weight or 0.0)
            if w > 0:
                result[symbol] = w
                reasons[symbol] = "override:force_in"
        elif action == "cap":
            if symbol in result and raw_weight is not None:
                capped = min(float(result[symbol]), float(raw_weight))
                if capped <= 0:
                    result.pop(symbol, None)
                else:
                    result[symbol] = capped
                reasons[symbol] = "override:cap"

    if audit and (result != before_snapshot or reasons):
        execute(
            """
            INSERT INTO operation_audit
                (audit_id, actor, action, target_type, target_id, reason, before_state, after_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                actor,
                "apply",
                "paper_override",
                sid,
                f"applied={len(reasons)}",
                str(before_snapshot),
                str(result),
            ),
            settings=settings,
        )
    return result, reasons
