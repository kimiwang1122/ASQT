"""Verified corporate actions used to explain adj_factor jumps.

The naive identity
    prev_close / close ≈ adj_factor / prev_adj_factor
is not used alone: cash dividends, same-day trading, and rounding break it.
A jump is explained only when a verified event matches the bar pair on
share ratio, theoretical ex-price, and price direction.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from asqt.config import Settings, get_settings
from asqt.symbols import limit_pct

FACTOR_TOLERANCE = 0.04
FACTOR_TOLERANCE_WITH_CASH = 0.12
PRICE_BAND_BUFFER = 0.02


def default_actions_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.project_root / "docs" / "p0" / "corporate_actions.csv"


def load_corporate_actions(
    path: Path | None = None,
    *,
    verified_only: bool = True,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    target = path or default_actions_path(settings)
    if not target.exists():
        return []
    with target.open(encoding="utf-8", newline="") as handle:
        rows = []
        for raw in csv.DictReader(handle):
            if verified_only and str(raw.get("verified", "")).strip() not in {"1", "true", "True"}:
                continue
            cash_per_10 = _num(raw.get("cash_per_10")) or 0.0
            bonus_per_10 = _num(raw.get("bonus_per_10")) or 0.0
            transfer_per_10 = _num(raw.get("transfer_per_10")) or 0.0
            share_ratio = _num(raw.get("share_ratio"))
            if share_ratio is None:
                share_ratio = 1.0 + (bonus_per_10 + transfer_per_10) / 10.0
            rows.append(
                {
                    "symbol": (raw.get("symbol") or "").strip(),
                    "ex_date": (raw.get("ex_date") or "").strip()[:10],
                    "action_type": (raw.get("action_type") or "").strip(),
                    "cash_per_share": cash_per_10 / 10.0,
                    "share_ratio": share_ratio,
                    "evidence_url": (raw.get("evidence_url") or "").strip(),
                }
            )
    return rows


def theoretical_ex_price(prev_close: float, cash_per_share: float, share_ratio: float) -> float | None:
    if share_ratio <= 0:
        return None
    value = (prev_close - cash_per_share) / share_ratio
    if value <= 0:
        return None
    return value


def action_explains_jump(prev: dict[str, Any], curr: dict[str, Any], action: dict[str, Any]) -> bool:
    if action.get("symbol") != curr.get("symbol"):
        return False
    if action.get("ex_date") != str(curr.get("trade_date") or "")[:10]:
        return False
    share_ratio = float(action.get("share_ratio") or 0)
    if share_ratio <= 1.01:
        return False
    prev_close = _num(prev.get("close"))
    curr_close = _num(curr.get("close"))
    prev_factor = _num(prev.get("adj_factor"))
    curr_factor = _num(curr.get("adj_factor"))
    if None in (prev_close, curr_close, prev_factor, curr_factor) or prev_factor == 0:
        return False
    if curr_close >= prev_close:
        return False
    factor_ratio = curr_factor / prev_factor
    cash = float(action.get("cash_per_share") or 0)
    factor_tol = FACTOR_TOLERANCE_WITH_CASH if cash > 0 else FACTOR_TOLERANCE
    if abs(factor_ratio / share_ratio - 1.0) > factor_tol:
        return False
    expected = theoretical_ex_price(prev_close, cash, share_ratio)
    if expected is None:
        return False
    band = limit_pct(str(curr.get("symbol"))) + PRICE_BAND_BUFFER
    if abs(curr_close / expected - 1.0) > band:
        return False
    return True


def find_explaining_action(
    prev: dict[str, Any],
    curr: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for action in actions:
        if action_explains_jump(prev, curr, action):
            return action
    return None


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
