"""ASQT symbol format: ``000001.SZ`` ↔ vendor ``sz.000001`` (incl. BJ)."""

from __future__ import annotations

import re

_SUFFIXES = frozenset({"SH", "SZ", "BJ"})
_VENDOR_PREFIX = {"sh": "SH", "sz": "SZ", "bj": "BJ"}
_DIGITS_6 = re.compile(r"^\d{6}$")


def split_symbol(symbol: str) -> tuple[str, str]:
    code, _, market = (symbol or "").partition(".")
    return code, market.upper()


def infer_market_from_code(code: str) -> str:
    """Infer exchange suffix from a 6-digit code (heuristic; prefer explicit suffix)."""
    if not _DIGITS_6.match(code or ""):
        raise ValueError(f"expected 6-digit code, got {code!r}")
    # Shanghai: main/STAR/funds
    if code.startswith(("60", "68", "69", "50", "51", "52", "56", "58")):
        return "SH"
    # Shenzhen: main/ChiNext/funds
    if code.startswith(("00", "30", "15", "16", "18", "12")):
        return "SZ"
    # Beijing Stock Exchange / NEEQ-style
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code[0] in {"6", "5", "9"}:
        return "SH"
    if code[0] in {"0", "1", "3"}:
        return "SZ"
    if code[0] in {"4", "8"}:
        return "BJ"
    raise ValueError(f"cannot infer market for code: {code}")


def normalize_symbol(symbol: str | None) -> str:
    """Normalize to ``XXXXXX.SH|SZ|BJ`` (uppercase suffix).

    Accepts:
    - ``000001.SZ`` / ``000001.sz``
    - BaoStock ``sz.000001`` / ``bj.920000``
    - bare ``000001`` (market inferred)
    """
    if symbol is None:
        raise ValueError("symbol is required")
    text = str(symbol).strip()
    if not text:
        raise ValueError("symbol is empty")

    lower = text.lower()
    if lower.startswith(("sh.", "sz.", "bj.")):
        prefix, _, number = lower.partition(".")
        market = _VENDOR_PREFIX.get(prefix)
        if market is None or not _DIGITS_6.match(number):
            raise ValueError(f"unsupported vendor code: {symbol}")
        return f"{number}.{market}"

    if "." in text:
        code, _, market = text.partition(".")
        market = market.upper()
        if market not in _SUFFIXES:
            raise ValueError(f"unsupported market suffix: {symbol}")
        if not _DIGITS_6.match(code):
            raise ValueError(f"expected 6-digit code: {symbol}")
        return f"{code}.{market}"

    if not _DIGITS_6.match(text):
        raise ValueError(f"unsupported symbol: {symbol}")
    return f"{text}.{infer_market_from_code(text)}"


def to_vendor_code(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    code, market = split_symbol(normalized)
    if market == "SH":
        return f"sh.{code}"
    if market == "SZ":
        return f"sz.{code}"
    if market == "BJ":
        return f"bj.{code}"
    raise ValueError(f"unsupported symbol: {symbol}")


def from_vendor_code(code: str) -> str:
    return normalize_symbol(code)


def infer_instrument_type(symbol: str) -> str:
    code = normalize_symbol(symbol).split(".", 1)[0]
    if code.startswith(("51", "52", "56", "58", "15", "16", "50")):
        return "etf"
    return "stock"


def infer_board(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    code, _, market = normalized.partition(".")
    if infer_instrument_type(normalized) == "etf":
        return "broad_index"
    if market == "BJ":
        return "bse"
    if code.startswith(("300", "301", "302")):
        return "chinext"
    if code.startswith("688") or code.startswith("689"):
        return "star"
    if market == "SH" and code.startswith("60"):
        return "main"
    if market == "SZ" and code.startswith(("000", "001", "002", "003")):
        return "main"
    return "main"


def limit_pct(symbol: str) -> float:
    board = infer_board(symbol)
    if board in {"chinext", "star"}:
        return 0.20
    if board == "bse":
        return 0.30
    return 0.10
