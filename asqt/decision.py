"""Structured decision ratings — five-tier / three-tier + REVIEW sentinel.

Rule strategies map weights onto the same vocabulary so console, alerts, and
(future) decision_log share one contract. Parse failure must surface as REVIEW,
never silently as Hold.
"""

from __future__ import annotations

from enum import Enum
import re
import unicodedata
from typing import Any


class PortfolioRating(str, Enum):
    """5-tier directional view (research / portfolio)."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier execution intent."""

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


RATING_REVIEW = "REVIEW"
RATINGS_5_TIER: tuple[str, ...] = tuple(item.value for item in PortfolioRating)
ACTIONS_3_TIER: tuple[str, ...] = tuple(item.value for item in TraderAction)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)
_RATING_WORD_RE = re.compile(r"\b(" + "|".join(RATINGS_5_TIER) + r")\b", re.IGNORECASE)


def is_review(value: str | None) -> bool:
    return str(value or "").strip().upper() == RATING_REVIEW


def extract_rating(text: str | None) -> str | None:
    """Extract a 5-tier rating from prose, or ``None`` if none is present.

    Callers that need a tradeable signal must map ``None`` → ``REVIEW`` (see
    ``rating_or_review``). Never invent Hold here.
    """
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", str(text))
    for line in norm.splitlines():
        match = _RATING_LABEL_RE.search(line)
        if match and match.group(1).lower() in _RATING_SET:
            return match.group(1).capitalize()
    match = _RATING_WORD_RE.search(norm)
    if match:
        word = match.group(1)
        for item in RATINGS_5_TIER:
            if item.lower() == word.lower():
                return item
    return None


def rating_or_review(text: str | None) -> str:
    """Deterministic signal: known 5-tier rating or ``REVIEW`` (never silent Hold)."""
    found = extract_rating(text)
    return found if found else RATING_REVIEW


def parse_rating(text: str | None, *, default: str = PortfolioRating.HOLD.value) -> str:
    """Legacy helper that always returns a 5-tier string (default Hold).

    Prefer ``rating_or_review`` for trading paths so ambiguity cannot become Hold.
    """
    found = extract_rating(text)
    return found if found else default


def weight_to_rating(weight: float | None) -> str:
    """Map a target weight to a 5-tier rating (rule strategies)."""
    if weight is None:
        return RATING_REVIEW
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return RATING_REVIEW
    if w > 0.15:
        return PortfolioRating.BUY.value
    if w > 0.05:
        return PortfolioRating.OVERWEIGHT.value
    if w < -0.15:
        return PortfolioRating.SELL.value
    if w < -0.05:
        return PortfolioRating.UNDERWEIGHT.value
    return PortfolioRating.HOLD.value


def rating_to_action(rating: str | None) -> str:
    """Collapse 5-tier (or REVIEW) to 3-tier trader action."""
    if is_review(rating) or not rating:
        return RATING_REVIEW
    text = str(rating).strip()
    if text in {PortfolioRating.BUY.value, PortfolioRating.OVERWEIGHT.value}:
        return TraderAction.BUY.value
    if text in {PortfolioRating.SELL.value, PortfolioRating.UNDERWEIGHT.value}:
        return TraderAction.SELL.value
    if text == PortfolioRating.HOLD.value:
        return TraderAction.HOLD.value
    # Unknown token → REVIEW (do not coerce to Hold)
    found = extract_rating(text)
    if not found:
        return RATING_REVIEW
    return rating_to_action(found)


def decision_from_targets(weights: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize a target-weight map into ratings (no LLM)."""
    if not weights:
        return {
            "rating": RATING_REVIEW,
            "action": RATING_REVIEW,
            "n": 0,
            "by_symbol": {},
        }
    by_symbol: dict[str, str] = {}
    for symbol, weight in weights.items():
        by_symbol[str(symbol)] = weight_to_rating(weight)
    # Gross directional hint: any Buy/Overweight → Buy; else any Sell → Sell; else Hold
    values = set(by_symbol.values())
    if RATING_REVIEW in values and len(values) == 1:
        rating = RATING_REVIEW
    elif values & {PortfolioRating.BUY.value, PortfolioRating.OVERWEIGHT.value}:
        rating = PortfolioRating.BUY.value
    elif values & {PortfolioRating.SELL.value, PortfolioRating.UNDERWEIGHT.value}:
        rating = PortfolioRating.SELL.value
    else:
        rating = PortfolioRating.HOLD.value
    return {
        "rating": rating,
        "action": rating_to_action(rating),
        "n": len(by_symbol),
        "by_symbol": by_symbol,
    }
