"""Deterministic digests for market / research rows."""

from __future__ import annotations

from hashlib import sha1
from typing import Any


def data_version_for(rows: list[dict[str, Any]]) -> str:
    """Stable short hash of symbol/date/close/adj/source/version rows."""
    digest = sha1()
    for row in sorted(rows, key=lambda item: (str(item["symbol"]), str(item["trade_date"]))):
        digest.update(
            f"{row['symbol']}|{row['trade_date']}|{row['close']}|{row['adj_factor']}|{row.get('source')}|{row.get('version')}".encode()
        )
    return digest.hexdigest()[:16]
