"""Declare which adapters provide which record schemas."""

from __future__ import annotations

from typing import Any

PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "baostock": {
        "source_id": "baostock",
        "name": "BaoStock",
        "provides": ("market_daily",),
    },
    "akshare": {
        "source_id": "akshare",
        "name": "AkShare",
        "provides": ("market_daily",),
    },
    "tushare": {
        "source_id": "tushare",
        "name": "Tushare",
        "provides": ("market_daily", "market_event"),
    },
}


def list_providers(*, schema: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for item in PROVIDER_REGISTRY.values():
        provides = tuple(item.get("provides") or ())
        if schema and schema not in provides:
            continue
        rows.append(
            {
                "source_id": item["source_id"],
                "name": item.get("name") or item["source_id"],
                "provides": list(provides),
            }
        )
    return rows


def provider_provides(source_id: str, schema: str) -> bool:
    item = PROVIDER_REGISTRY.get(str(source_id or "").strip())
    if not item:
        return False
    return schema in tuple(item.get("provides") or ())


def providers_for(schema: str) -> list[str]:
    return [row["source_id"] for row in list_providers(schema=schema)]
