"""ASQT symbol format: 000001.SZ  <->  vendor sz.000001."""

from __future__ import annotations


def to_vendor_code(symbol: str) -> str:
    code, _, market = symbol.partition(".")
    market = market.upper()
    if market == "SH":
        return f"sh.{code}"
    if market == "SZ":
        return f"sz.{code}"
    raise ValueError(f"unsupported symbol: {symbol}")


def from_vendor_code(code: str) -> str:
    prefix, _, number = code.partition(".")
    prefix = prefix.lower()
    if prefix == "sh":
        return f"{number}.SH"
    if prefix == "sz":
        return f"{number}.SZ"
    raise ValueError(f"unsupported vendor code: {code}")


def split_symbol(symbol: str) -> tuple[str, str]:
    code, _, market = (symbol or "").partition(".")
    return code, market.upper()


def infer_instrument_type(symbol: str) -> str:
    code = symbol.split(".", 1)[0]
    if code.startswith(("51", "52", "56", "58", "15", "16", "50")):
        return "etf"
    return "stock"


def infer_board(symbol: str) -> str:
    code, _, market = symbol.partition(".")
    if infer_instrument_type(symbol) == "etf":
        if code.startswith("51") and code[2:4] in {"03", "05", "00"}:
            return "broad_index"
        if code.startswith("15") and code[2:4] in {"99", "15"}:
            return "broad_index"
        if code.startswith("58"):
            return "broad_index"
        return "broad_index"
    if code.startswith("300") or code.startswith("301"):
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
    return 0.10
