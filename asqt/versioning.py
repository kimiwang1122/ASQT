"""Deterministic digests for market rows and long-running job configs."""

from __future__ import annotations

import json
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


def run_signature(kind: str, params: dict[str, Any] | None = None) -> str:
    """Canonical fingerprint for a job config (GATE-D5).

    Same kind+params → identical signature; any material field change → new hash.
    """
    payload = {"kind": str(kind or "").strip(), **_canonicalize(params or {})}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha1(text.encode()).hexdigest()[:16]


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonicalize(value[k]) for k in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value)


class SignatureMismatch(ValueError):
    """Raised when resuming a run with a drifted configuration fingerprint."""

    def __init__(self, *, expected: str, actual: str, run_id: str | None = None) -> None:
        self.expected = expected
        self.actual = actual
        self.run_id = run_id
        where = f" run_id={run_id}" if run_id else ""
        super().__init__(f"run signature mismatch{where}: expected={expected} actual={actual}")


def assert_run_signature(
    expected: str | None,
    actual: str | None,
    *,
    run_id: str | None = None,
) -> None:
    """Refuse config-drift resume: signatures must both be present and equal."""
    exp = str(expected or "").strip()
    act = str(actual or "").strip()
    if not exp or not act or exp != act:
        raise SignatureMismatch(expected=exp or "<missing>", actual=act or "<missing>", run_id=run_id)
