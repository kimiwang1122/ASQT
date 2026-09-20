"""Symbol tags / stock pools for universe sync and strategy pool filters."""

from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import execute, executemany, initialize_database, query_all

UNIVERSE_CSV_SOURCE = "universe_csv"


def _normalize_tags(tags: str | Iterable[str] | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        items = [tags]
    else:
        items = list(tags)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = str(item or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def resolve_pool(
    tags: str | Iterable[str] | None,
    *,
    settings: Settings | None = None,
) -> set[str]:
    """Return symbols that carry any of the given tags (union)."""
    settings = settings or get_settings()
    initialize_database(settings)
    tag_list = _normalize_tags(tags)
    if not tag_list:
        return set()
    placeholders = ", ".join("?" for _ in tag_list)
    rows = query_all(
        f"SELECT DISTINCT symbol FROM symbol_tag WHERE tag IN ({placeholders})",
        tuple(tag_list),
        settings=settings,
    )
    return {str(row["symbol"]) for row in rows}


def _tag_where(
    *,
    tag: str | None = None,
    symbol: str | None = None,
    source: str | None = None,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if tag:
        clauses.append("tag = ?")
        params.append(tag.strip())
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.strip())
    if source:
        clauses.append("source = ?")
        params.append(source.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def count_tags(
    *,
    tag: str | None = None,
    symbol: str | None = None,
    source: str | None = None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    initialize_database(settings)
    where, params = _tag_where(tag=tag, symbol=symbol, source=source)
    rows = query_all(
        f"SELECT COUNT(*) AS c FROM symbol_tag {where}",
        tuple(params),
        settings=settings,
    )
    return int(rows[0]["c"]) if rows else 0


def summarize_tags(
    *,
    tag: str | None = None,
    symbol: str | None = None,
    source: str | None = None,
    limit: int = 12,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    initialize_database(settings)
    where, params = _tag_where(tag=tag, symbol=symbol, source=source)
    params.append(max(1, int(limit)))
    return query_all(
        f"""
        SELECT tag, COUNT(*) AS count
        FROM symbol_tag
        {where}
        GROUP BY tag
        ORDER BY count DESC, tag
        LIMIT ?
        """,
        tuple(params),
        settings=settings,
    )


def list_tags(
    *,
    tag: str | None = None,
    symbol: str | None = None,
    source: str | None = None,
    limit: int = 5000,
    offset: int = 0,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    initialize_database(settings)
    where, params = _tag_where(tag=tag, symbol=symbol, source=source)
    params.extend([max(1, int(limit)), max(0, int(offset))])
    return query_all(
        f"SELECT * FROM symbol_tag {where} ORDER BY tag, symbol LIMIT ? OFFSET ?",
        tuple(params),
        settings=settings,
    )


def list_pool(
    tag: str,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    tag_key = (tag or "").strip()
    if not tag_key:
        raise ValueError("tag is required")
    return list_tags(tag=tag_key, settings=settings)


def upsert_tags(
    rows: list[dict[str, Any]],
    *,
    actor: str = "operator",
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Upsert symbol_tag rows; writes operation_audit."""
    settings = settings or get_settings()
    initialize_database(settings)
    if not rows:
        return []
    prepared: list[tuple[str, str, str, str | None]] = []
    for raw in rows:
        tag = str(raw.get("tag") or "").strip()
        symbol = str(raw.get("symbol") or "").strip()
        source = str(raw.get("source") or "manual").strip() or "manual"
        note = raw.get("note")
        note_text = None if note is None else str(note).strip() or None
        if not tag or not symbol:
            raise ValueError("tag and symbol are required")
        prepared.append((tag, symbol, source, note_text))

    before_keys = {(row[0], row[1]) for row in prepared}
    existing = {
        (str(row["tag"]), str(row["symbol"])): dict(row)
        for row in list_tags(limit=50_000, settings=settings)
        if (str(row["tag"]), str(row["symbol"])) in before_keys
    }
    executemany(
        """
        INSERT INTO symbol_tag (tag, symbol, source, note, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(tag, symbol) DO UPDATE SET
            source = excluded.source,
            note = excluded.note,
            updated_at = CURRENT_TIMESTAMP
        """,
        prepared,
        settings=settings,
    )
    after_rows = list_tags(limit=50_000, settings=settings)
    result = [
        dict(row)
        for row in after_rows
        if (str(row["tag"]), str(row["symbol"])) in before_keys
    ]
    for tag, symbol, source, note in prepared:
        key = (tag, symbol)
        before = existing.get(key)
        after = next((item for item in result if item["tag"] == tag and item["symbol"] == symbol), None)
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
                "symbol_tag",
                f"{tag}:{symbol}",
                f"source={source}",
                None if before is None else str(before),
                None if after is None else str(after),
            ),
            settings=settings,
        )
    return result


def sync_universe_tags(
    rows: list[dict[str, str]],
    *,
    settings: Settings | None = None,
) -> int:
    """Replace all universe_csv tags from universe CSV pool column."""
    settings = settings or get_settings()
    initialize_database(settings)
    execute(
        "DELETE FROM symbol_tag WHERE source = ?",
        (UNIVERSE_CSV_SOURCE,),
        settings=settings,
    )
    payload: list[tuple[str, str, str, str | None]] = []
    for row in rows:
        tag = str(row.get("pool") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        if not tag or not symbol:
            continue
        note = str(row.get("reason") or "").strip() or None
        payload.append((tag, symbol, UNIVERSE_CSV_SOURCE, note))
    if payload:
        executemany(
            """
            INSERT INTO symbol_tag (tag, symbol, source, note, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            payload,
            settings=settings,
        )
    return len(payload)
