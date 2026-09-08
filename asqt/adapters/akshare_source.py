"""AkShare DataSourceAdapter. Vendor SDK stays in this module."""

from __future__ import annotations

from typing import Any

from asqt.symbols import infer_instrument_type


class AkShareAdapter:
    source_id = "akshare"

    def health(self) -> dict[str, Any]:
        try:
            import akshare as ak  # noqa: F401
        except ImportError:
            return {
                "source_id": self.source_id,
                "ok": False,
                "error_msg": "akshare is not installed; pip install -e '.[data]'",
            }
        return {"source_id": self.source_id, "ok": True}

    def fetch_market_daily(
        self,
        symbols: list[str],
        start: str,
        end: str,
        on_progress=None,
    ) -> list[dict[str, Any]]:
        ak = _ak()
        start_compact = start.replace("-", "")
        end_compact = end.replace("-", "")
        rows: list[dict[str, Any]] = []
        self.last_errors = []
        total = len(symbols)
        for index, symbol in enumerate(symbols, 1):
            try:
                rows.extend(self._fetch_one(ak, symbol, start_compact, end_compact))
            except Exception as exc:
                self.last_errors.append({"symbol": symbol, "error": str(exc)[:300]})
            if on_progress:
                on_progress(index, total, symbol)
        return rows

    def fetch_trade_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        ak = _ak()
        frame = ak.tool_trade_date_hist_sina()
        dates = [_iso_date(_first(row, "trade_date", "交易日")) for row in _records(frame)]
        dates = [day for day in dates if day and start <= day <= end]
        return [{"trade_date": day, "market": "CN", "is_open": 1} for day in dates]

    def _fetch_one(self, ak: Any, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
        code = symbol.split(".", 1)[0]
        raw = self._hist(ak, symbol, code, start, end, adjust="")
        hfq = {
            _iso_date(_first(row, "date", "日期")): _to_float(_first(row, "close", "收盘"))
            for row in self._hist(ak, symbol, code, start, end, adjust="hfq")
        }
        packed = []
        for row in raw:
            trade_date = _iso_date(_first(row, "date", "日期"))
            close = _to_float(_first(row, "close", "收盘"))
            backward = hfq.get(trade_date)
            adj_factor = None
            if close not in (None, 0) and backward not in (None, 0):
                adj_factor = backward / close
            volume = _to_float(_first(row, "volume", "成交量"))
            packed.append(
                {
                    "symbol": symbol,
                    "date": trade_date,
                    "open": _first(row, "open", "开盘"),
                    "high": _first(row, "high", "最高"),
                    "low": _first(row, "low", "最低"),
                    "close": _first(row, "close", "收盘"),
                    "volume": None if volume is None else int(volume * 100),
                    "amount": _first(row, "amount", "成交额"),
                    "preclose": None,
                    "tradestatus": "1",
                    "isST": "0",
                    "adj_factor": adj_factor,
                    "name": None,
                    "ipoDate": None,
                    "outDate": None,
                    "status": "1",
                }
            )
        return packed

    def _hist(self, ak: Any, symbol: str, code: str, start: str, end: str, *, adjust: str) -> list[dict[str, Any]]:
        if infer_instrument_type(symbol) == "etf":
            frame = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust=adjust,
            )
        else:
            frame = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust=adjust,
            )
        return _records(frame)


def _ak() -> Any:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare is not installed; pip install -e '.[data]'") from exc
    return ak


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    if isinstance(frame, list):
        return frame
    return []


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _iso_date(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan"}:
        return None
    return float(text)
