"""BaoStock DataSourceAdapter. Vendor SDK stays in this module."""

from __future__ import annotations

import socket
from typing import Any

from asqt.symbols import from_vendor_code, to_vendor_code


class BaoStockAdapter:
    source_id = "baostock"

    def __init__(self) -> None:
        self._client = None

    def _bs(self):
        if self._client is None:
            try:
                import baostock as bs  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "baostock is not installed; pip install -e '.[data]'"
                ) from exc
            self._client = bs
        return self._client

    def health(self) -> dict[str, Any]:
        bs = self._bs()
        login = bs.login()
        ok = getattr(login, "error_code", "1") == "0"
        if ok:
            bs.logout()
        return {
            "source_id": self.source_id,
            "ok": ok,
            "error_code": getattr(login, "error_code", None),
            "error_msg": getattr(login, "error_msg", None),
        }

    def fetch_market_daily(
        self,
        symbols: list[str],
        start: str,
        end: str,
        on_progress=None,
    ) -> list[dict[str, Any]]:
        bs = self._bs()
        login = bs.login()
        if getattr(login, "error_code", "1") != "0":
            raise RuntimeError(f"baostock login failed: {getattr(login, 'error_msg', login)}")
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(30)
        try:
            rows: list[dict[str, Any]] = []
            self.last_errors = []
            total = len(symbols)
            for index, symbol in enumerate(symbols, 1):
                try:
                    rows.extend(self._fetch_one(bs, symbol, start, end))
                except Exception as exc:  # noqa: BLE001
                    self.last_errors.append({"symbol": symbol, "error": str(exc)[:300]})
                if on_progress:
                    on_progress(index, total, symbol)
            return rows
        finally:
            socket.setdefaulttimeout(previous_timeout)
            bs.logout()

    def fetch_trade_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        bs = self._bs()
        login = bs.login()
        if getattr(login, "error_code", "1") != "0":
            raise RuntimeError(f"baostock login failed: {getattr(login, 'error_msg', login)}")
        try:
            result = bs.query_trade_dates(start_date=start, end_date=end)
            rows = _read_result(result)
            out = []
            for row in rows:
                trade_date = _iso_date(row.get("calendar_date") or row.get("date"))
                is_open = str(row.get("is_trading_day", "0")).strip() in {"1", "true", "True"}
                out.append({"trade_date": trade_date, "market": "CN", "is_open": int(is_open)})
            return out
        finally:
            bs.logout()

    def _fetch_one(self, bs: Any, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
        vendor = to_vendor_code(symbol)
        fields = (
            "date,code,open,high,low,close,preclose,volume,amount,"
            "adjustflag,tradestatus,pctChg,isST"
        )
        raw_rows = _read_result(
            bs.query_history_k_data_plus(
                vendor,
                fields,
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="3",
            )
        )
        adj_rows = _read_result(
            bs.query_history_k_data_plus(
                vendor,
                "date,close",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="1",
            )
        )
        adj_close = {_iso_date(row.get("date")): _to_float(row.get("close")) for row in adj_rows}
        basic = _read_result(bs.query_stock_basic(code=vendor))
        profile = basic[0] if basic else {}
        packed = []
        for row in raw_rows:
            trade_date = _iso_date(row.get("date"))
            close = _to_float(row.get("close"))
            backward = adj_close.get(trade_date)
            adj_factor = None
            if close not in (None, 0) and backward not in (None, 0):
                adj_factor = backward / close
            packed.append(
                {
                    "symbol": from_vendor_code(str(row.get("code") or vendor)),
                    "vendor_code": row.get("code") or vendor,
                    "date": trade_date,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "preclose": row.get("preclose"),
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                    "tradestatus": row.get("tradestatus"),
                    "isST": row.get("isST"),
                    "pctChg": row.get("pctChg"),
                    "adjustflag": row.get("adjustflag"),
                    "adj_close_backward": backward,
                    "adj_factor": adj_factor,
                    "name": profile.get("code_name"),
                    "ipoDate": profile.get("ipoDate"),
                    "outDate": profile.get("outDate"),
                    "status": profile.get("status"),
                    "type": profile.get("type"),
                }
            )
        return packed


def _read_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    error_code = getattr(result, "error_code", "0")
    if error_code not in {"0", 0, None}:
        raise RuntimeError(f"baostock query failed: {getattr(result, 'error_msg', error_code)}")
    fields = list(getattr(result, "fields", []) or [])
    rows: list[dict[str, Any]] = []
    while getattr(result, "error_code", "1") == "0" and result.next():
        values = result.get_row_data()
        rows.append({fields[index]: values[index] if index < len(values) else None for index in range(len(fields))})
    return rows


def _iso_date(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    return text[:10]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan"}:
        return None
    return float(text)
