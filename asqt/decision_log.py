"""Paper decision log: pending → resolved with PIT-safe queries (SQLite only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import execute, initialize_database, query_all
from asqt.decision import decision_from_targets
from asqt.pit import on_or_before, parse_asof

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _loads(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def record_pending(
    *,
    strategy_id: str,
    signal_date: str,
    weights: dict[str, float],
    strategy_version: str | None = None,
    data_version: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Upsert a pending decision for ``strategy_id`` + ``signal_date`` (idempotent)."""
    settings = settings or get_settings()
    initialize_database(settings)
    sid = (strategy_id or "").strip()
    asof = parse_asof(signal_date)
    if not sid:
        raise ValueError("strategy_id is required")

    existing = query_all(
        """
        SELECT * FROM decision_log
        WHERE strategy_id = ? AND signal_date = ? AND status = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (sid, asof, STATUS_PENDING),
        settings=settings,
    )
    summary = decision_from_targets(weights)
    thesis = {
        "weights": {str(k): float(v) for k, v in (weights or {}).items()},
        "rating": summary["rating"],
        "action": summary["action"],
        "strategy_version": strategy_version,
        "data_version": data_version,
        "n": summary["n"],
    }
    if existing:
        decision_id = str(existing[0]["decision_id"])
        execute(
            """
            UPDATE decision_log
            SET rating = ?, action = ?, thesis_json = ?
            WHERE decision_id = ?
            """,
            (
                summary["rating"],
                summary["action"],
                _dumps(thesis),
                decision_id,
            ),
            settings=settings,
        )
        row = get_decision(decision_id, settings=settings)
        assert row is not None
        return row

    decision_id = str(uuid4())
    execute(
        """
        INSERT INTO decision_log
            (decision_id, strategy_id, signal_date, fill_date, status, rating, action,
             thesis_json, outcome_json, resolved_at, lesson, created_at)
        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL, NULL, ?)
        """,
        (
            decision_id,
            sid,
            asof,
            STATUS_PENDING,
            summary["rating"],
            summary["action"],
            _dumps(thesis),
            _now(),
        ),
        settings=settings,
    )
    row = get_decision(decision_id, settings=settings)
    assert row is not None
    return row


def resolve_for_session(
    *,
    strategy_id: str,
    signal_date: str,
    fill_date: str,
    nav_before: float | None,
    nav_after: float | None,
    halted: bool = False,
    halt_reason: str | None = None,
    order_ids: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Resolve the pending decision for signal_date after the fill session."""
    settings = settings or get_settings()
    initialize_database(settings)
    sid = (strategy_id or "").strip()
    signal = parse_asof(signal_date)
    fill = parse_asof(fill_date)
    rows = query_all(
        """
        SELECT * FROM decision_log
        WHERE strategy_id = ? AND signal_date = ? AND status = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (sid, signal, STATUS_PENDING),
        settings=settings,
    )
    if not rows:
        return None
    decision_id = str(rows[0]["decision_id"])
    ret = None
    if nav_before and nav_before > 0 and nav_after is not None:
        ret = float(nav_after) / float(nav_before) - 1.0
    outcome = {
        "fill_date": fill,
        "nav_before": nav_before,
        "nav_after": nav_after,
        "session_return": ret,
        "halted": bool(halted),
        "halt_reason": halt_reason,
        "order_ids": list(order_ids or []),
    }
    lesson = _lesson_template(ret, halted=halted, halt_reason=halt_reason)
    execute(
        """
        UPDATE decision_log
        SET status = ?, fill_date = ?, outcome_json = ?, resolved_at = ?, lesson = ?
        WHERE decision_id = ?
        """,
        (STATUS_RESOLVED, fill, _dumps(outcome), fill, lesson, decision_id),
        settings=settings,
    )
    return get_decision(decision_id, settings=settings)


def _lesson_template(session_return: float | None, *, halted: bool, halt_reason: str | None) -> str:
    parts: list[str] = []
    if session_return is None:
        parts.append("会话收益未知")
    else:
        parts.append(f"会话收益 {session_return * 100:+.2f}%")
    if halted:
        parts.append(f"触发急停/平仓({halt_reason or 'halt'})")
    else:
        parts.append("未触发急停")
    return "；".join(parts)


def get_decision(decision_id: str, *, settings: Settings | None = None) -> dict[str, Any] | None:
    rows = query_all(
        "SELECT * FROM decision_log WHERE decision_id = ?",
        (decision_id,),
        settings=settings,
    )
    if not rows:
        return None
    return _public_row(rows[0])


def list_decisions(
    *,
    strategy_id: str | None = None,
    asof: str | None = None,
    status: str | None = None,
    limit: int = 50,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """List decisions with optional PIT filter.

    When ``asof`` is set:
    - pending visible only if ``signal_date <= asof``
    - resolved visible only if ``resolved_at <= asof``
    Unresolved future lessons (signal_date > asof) are hidden.
    """
    settings = settings or get_settings()
    initialize_database(settings)
    limit = max(1, min(int(limit or 50), 200))
    clauses: list[str] = []
    params: list[Any] = []
    if strategy_id:
        clauses.append("strategy_id = ?")
        params.append(strategy_id.strip())
    if status:
        clauses.append("status = ?")
        params.append(status.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = query_all(
        f"""
        SELECT * FROM decision_log
        {where}
        ORDER BY signal_date DESC, created_at DESC
        LIMIT ?
        """,
        tuple(params + [limit * 3]),  # over-fetch then PIT-filter
        settings=settings,
    )
    out: list[dict[str, Any]] = []
    cutoff = parse_asof(asof) if asof else None
    for row in rows:
        pub = _public_row(row)
        if cutoff:
            if pub["status"] == STATUS_PENDING:
                if not on_or_before(pub.get("signal_date"), cutoff):
                    continue
            else:
                resolved = pub.get("resolved_at") or pub.get("fill_date")
                if not resolved or not on_or_before(resolved, cutoff):
                    continue
        out.append(pub)
        if len(out) >= limit:
            break
    return out


def attach_decision_to_targets(
    *,
    strategy_id: str,
    signal_date: str,
    decision_id: str,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    execute(
        """
        UPDATE target_position
        SET decision_id = ?
        WHERE strategy_id = ? AND trade_date = ?
        """,
        (decision_id, strategy_id, parse_asof(signal_date)),
        settings=settings,
    )
    rows = query_all(
        "SELECT COUNT(*) AS c FROM target_position WHERE strategy_id = ? AND trade_date = ? AND decision_id = ?",
        (strategy_id, parse_asof(signal_date), decision_id),
        settings=settings,
    )
    return int(rows[0]["c"]) if rows else 0


def snapshot_nav(account_id: str, trade_date: str, *, settings: Settings | None = None) -> float | None:
    rows = query_all(
        """
        SELECT total_asset FROM account_snapshot
        WHERE account_id = ? AND trade_date = ?
        """,
        (account_id, parse_asof(trade_date)),
        settings=settings,
    )
    if not rows:
        # fall back to latest snapshot on/before date
        rows = query_all(
            """
            SELECT total_asset FROM account_snapshot
            WHERE account_id = ? AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT 1
            """,
            (account_id, parse_asof(trade_date)),
            settings=settings,
        )
    if not rows or rows[0]["total_asset"] is None:
        return None
    return float(rows[0]["total_asset"])


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["thesis"] = _loads(out.pop("thesis_json", None))
    out["outcome"] = _loads(out.pop("outcome_json", None))
    return out
