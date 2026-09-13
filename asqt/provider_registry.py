"""Declare which adapters provide which record schemas (priority / optional).

Expanding a schema capability is declaration-only here; callers use
``providers_for`` / ``resolve_provider_chain`` instead of hard-coded source lists.
"""

from __future__ import annotations

from typing import Any, Callable

PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "baostock": {
        "source_id": "baostock",
        "name": "BaoStock",
        "priority": 10,
        "optional": False,
        "provides": ("market_daily",),
    },
    "akshare": {
        "source_id": "akshare",
        "name": "AkShare",
        "priority": 20,
        "optional": True,
        "provides": ("market_daily",),
    },
    "tushare": {
        "source_id": "tushare",
        "name": "Tushare",
        "priority": 15,
        "optional": True,
        "provides": ("market_daily", "market_event"),
    },
}


def _public_row(item: dict[str, Any]) -> dict[str, Any]:
    provides = tuple(item.get("provides") or ())
    return {
        "source_id": item["source_id"],
        "name": item.get("name") or item["source_id"],
        "priority": int(item.get("priority") if item.get("priority") is not None else 100),
        "optional": bool(item.get("optional", False)),
        "provides": list(provides),
    }


def list_providers(
    *,
    schema: str | None = None,
    include_optional: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in PROVIDER_REGISTRY.values():
        provides = tuple(item.get("provides") or ())
        if schema and schema not in provides:
            continue
        row = _public_row(item)
        if not include_optional and row["optional"]:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row["priority"], row["source_id"]))
    return rows


def provider_provides(source_id: str, schema: str) -> bool:
    item = PROVIDER_REGISTRY.get(str(source_id or "").strip())
    if not item:
        return False
    return schema in tuple(item.get("provides") or ())


def providers_for(schema: str, *, include_optional: bool = True) -> list[str]:
    return [row["source_id"] for row in list_providers(schema=schema, include_optional=include_optional)]


def resolve_provider_chain(
    schema: str,
    *,
    preferred: str | None = None,
    include_optional: bool = True,
) -> list[dict[str, Any]]:
    """Ordered provider metadata for a schema (required first by priority, then optional).

    If ``preferred`` is set and provides the schema, it is moved to the front.
    """
    chain = list_providers(schema=schema, include_optional=include_optional)
    pref = (preferred or "").strip()
    if not pref:
        return chain
    if not provider_provides(pref, schema):
        return chain
    head = [row for row in chain if row["source_id"] == pref]
    tail = [row for row in chain if row["source_id"] != pref]
    return head + tail


def fetch_with_fallback(
    schema: str,
    fetch_fn: Callable[[str], Any],
    *,
    preferred: str | None = None,
    include_optional: bool = True,
) -> dict[str, Any]:
    """Try providers in chain order until ``fetch_fn(source_id)`` succeeds.

    ``fetch_fn`` should raise on failure. Returns
    ``{ok, source_id, result, tried, errors, fallback_from}``.
    """
    chain = resolve_provider_chain(schema, preferred=preferred, include_optional=include_optional)
    tried: list[str] = []
    errors: list[dict[str, str]] = []
    for row in chain:
        source_id = row["source_id"]
        tried.append(source_id)
        try:
            result = fetch_fn(source_id)
        except Exception as exc:  # noqa: BLE001 — collect and continue chain
            errors.append({"source_id": source_id, "error": str(exc)})
            continue
        fallback_from = tried[0] if len(tried) > 1 else None
        return {
            "ok": True,
            "source_id": source_id,
            "result": result,
            "tried": tried,
            "errors": errors,
            "fallback_from": fallback_from,
        }
    return {
        "ok": False,
        "source_id": None,
        "result": None,
        "tried": tried,
        "errors": errors,
        "fallback_from": None,
    }
