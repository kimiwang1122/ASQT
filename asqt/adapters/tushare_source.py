"""Tushare DataSourceAdapter. Token stays in env / data/.tushare_token, not in source."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from asqt.symbols import infer_instrument_type

REST_URL = "https://api.tushare.pro"
MCP_URL = "https://api.tushare.pro/mcp/"
DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,vol,amount"
# 5000+ 积分档官方约 500 次/分钟；默认按约 300 次/分钟留余量。
DEFAULT_THROTTLE_S = 0.2
# Official stk_holdertrade cap: 3000 rows per request.
STK_HOLDERTRADE_MAX_ROWS = 3000
# Default lookback when start/end omitted (full history is too slow; pass start for longer).
DEFAULT_HOLDERTRADE_LOOKBACK_DAYS = 730
DEFAULT_HOLDERTRADE_START = "2010-01-01"  # used only when explicitly requested via long start
HOLDERTRADE_FIELDS = (
    "ts_code,ann_date,holder_name,holder_type,in_de,change_vol,change_ratio,"
    "after_share,after_ratio,avg_price,total_share,begin_date,close_date"
)


def _parse_iso_date(value: str | None, *, fallback: date) -> date:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    return fallback


def _compact_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def iter_month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Inclusive month slices covering [start, end]."""
    if end < start:
        return []
    windows: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last_day = monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, last_day)
        win_start = max(start, cursor)
        win_end = min(end, month_end)
        if win_start <= win_end:
            windows.append((win_start, win_end))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return windows


def iter_day_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Inclusive one-day slices covering [start, end]."""
    if end < start:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        windows.append((cursor, cursor))
        cursor += timedelta(days=1)
    return windows


class TushareAdapter:
    source_id = "tushare"

    def __init__(self, token: str | None = None, *, timeout: int = 60) -> None:
        self._token = (token or "").strip() or None
        self.timeout = timeout
        self.throttle_s = DEFAULT_THROTTLE_S
        self.last_errors: list[dict[str, str]] = []
        self._skip_apis: set[str] = set()
        self.last_holdertrade_meta: dict[str, Any] = {}

    def health(self) -> dict[str, Any]:
        try:
            self._token_value()
        except RuntimeError as exc:
            return {"source_id": self.source_id, "ok": False, "error_msg": str(exc)}
        try:
            rows = self._query("daily", {"ts_code": "000001.SZ", "start_date": "20260901", "end_date": "20260907"}, "ts_code,trade_date,close")
            sample = rows[0] if rows else {}
            return {
                "source_id": self.source_id,
                "ok": bool(rows),
                "via": "rest",
                "sample": {"ts_code": sample.get("ts_code"), "trade_date": sample.get("trade_date"), "close": sample.get("close")},
            }
        except Exception as rest_exc:  # noqa: BLE001
            return {"source_id": self.source_id, "ok": False, "error_msg": str(rest_exc)[:300]}

    def fetch_market_daily(
        self,
        symbols: list[str],
        start: str,
        end: str,
        on_progress=None,
    ) -> list[dict[str, Any]]:
        start_compact = start.replace("-", "")
        end_compact = end.replace("-", "")
        rows: list[dict[str, Any]] = []
        self.last_errors = []
        self._skip_apis = set()
        total = len(symbols)
        for index, symbol in enumerate(symbols, 1):
            try:
                rows.extend(self._fetch_one(symbol, start_compact, end_compact))
            except Exception as exc:  # noqa: BLE001
                self.last_errors.append({"symbol": symbol, "error": str(exc)[:300]})
            if on_progress:
                on_progress(index, total, symbol)
            if index < total and self.throttle_s:
                time.sleep(self.throttle_s)
        return rows

    def fetch_trade_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        rows = self._query(
            "trade_cal",
            {
                "exchange": "SSE",
                "start_date": start.replace("-", ""),
                "end_date": end.replace("-", ""),
                "is_open": "1",
            },
            "cal_date,is_open",
        )
        out = []
        for row in rows:
            day = _iso_date(row.get("cal_date"))
            if day:
                out.append({"trade_date": day, "market": "CN", "is_open": 1})
        return out

    def _fetch_one(self, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
        kind = infer_instrument_type(symbol)
        if kind == "etf":
            bars = self._query_bars(["fund_daily", "daily"], symbol, start, end)
        else:
            bars = self._query_bars(["daily"], symbol, start, end)
        factors = self._query_factors("fund_adj" if kind == "etf" else "adj_factor", symbol, start, end)
        packed = []
        for row in bars:
            trade_date = _iso_date(row.get("trade_date"))
            volume = _to_float(row.get("vol"))
            amount = _to_float(row.get("amount"))
            packed.append(
                {
                    "symbol": symbol,
                    "vendor_code": row.get("ts_code") or symbol,
                    "date": trade_date,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "preclose": row.get("pre_close"),
                    "volume": None if volume is None else int(volume * 100),
                    "amount": None if amount is None else amount * 1000,
                    "tradestatus": "1",
                    "adj_factor": factors.get(trade_date),
                    "status": "1",
                    "type": kind,
                }
            )
        return packed

    def fetch_stk_holdertrade(
        self,
        symbols: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        *,
        trade_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch shareholder increase/decrease rows (Tushare stk_holdertrade).

        Tushare caps each call at 3000 rows. We page by calendar month and, if a
        month still hits the cap, subdivide by day. Default range is
        2010-01-01 → today when start/end are omitted.
        """
        self.last_errors = []
        today = date.today()
        if start:
            start_d = _parse_iso_date(start, fallback=today - timedelta(days=DEFAULT_HOLDERTRADE_LOOKBACK_DAYS))
        else:
            start_d = today - timedelta(days=DEFAULT_HOLDERTRADE_LOOKBACK_DAYS)
        end_d = _parse_iso_date(end, fallback=today)
        if end_d < start_d:
            start_d, end_d = end_d, start_d
        wanted = [str(item).strip() for item in (symbols or []) if str(item).strip()]
        self.last_holdertrade_meta = {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "symbols": wanted,
            "default_lookback_days": None if start else DEFAULT_HOLDERTRADE_LOOKBACK_DAYS,
            "chunks": 0,
            "chunk_hits_limit": [],
            "day_hits_limit": [],
            "requests": 0,
        }
        rows: list[dict[str, Any]] = []
        if wanted:
            total = len(wanted)
            for index, symbol in enumerate(wanted, 1):
                base: dict[str, Any] = {"ts_code": symbol}
                if trade_type:
                    base["trade_type"] = trade_type
                rows.extend(self._fetch_holdertrade_range(base, start_d, end_d))
                if index < total and self.throttle_s:
                    time.sleep(self.throttle_s)
        else:
            base = {}
            if trade_type:
                base["trade_type"] = trade_type
            rows.extend(self._fetch_holdertrade_range(base, start_d, end_d))
        deduped = _dedupe_holdertrade_rows(rows)
        self.last_holdertrade_meta["fetched_raw"] = len(rows)
        self.last_holdertrade_meta["fetched_deduped"] = len(deduped)
        return deduped

    def _fetch_holdertrade_range(
        self,
        base_params: dict[str, Any],
        start_d: date,
        end_d: date,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        windows = iter_month_windows(start_d, end_d)
        for index, (win_start, win_end) in enumerate(windows):
            if index and self.throttle_s:
                time.sleep(self.throttle_s)
            chunk = self._query_holdertrade_window(base_params, win_start, win_end)
            if len(chunk) >= STK_HOLDERTRADE_MAX_ROWS and win_start < win_end:
                label = f"{win_start.isoformat()}~{win_end.isoformat()}"
                self.last_holdertrade_meta.setdefault("chunk_hits_limit", []).append(label)
                out.extend(self._fetch_holdertrade_by_day(base_params, win_start, win_end))
            else:
                if len(chunk) >= STK_HOLDERTRADE_MAX_ROWS:
                    self.last_holdertrade_meta.setdefault("day_hits_limit", []).append(win_start.isoformat())
                out.extend(chunk)
        return out

    def _fetch_holdertrade_by_day(
        self,
        base_params: dict[str, Any],
        start_d: date,
        end_d: date,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for index, (day_start, day_end) in enumerate(iter_day_windows(start_d, end_d)):
            if index and self.throttle_s:
                time.sleep(self.throttle_s)
            chunk = self._query_holdertrade_window(base_params, day_start, day_end)
            if len(chunk) >= STK_HOLDERTRADE_MAX_ROWS:
                self.last_holdertrade_meta.setdefault("day_hits_limit", []).append(day_start.isoformat())
                self.last_errors.append(
                    {
                        "symbol": str(base_params.get("ts_code") or "*"),
                        "error": (
                            f"stk_holdertrade still capped at {STK_HOLDERTRADE_MAX_ROWS} "
                            f"on {day_start.isoformat()}"
                        ),
                    }
                )
            out.extend(chunk)
        return out

    def _query_holdertrade_window(
        self,
        base_params: dict[str, Any],
        start_d: date,
        end_d: date,
    ) -> list[dict[str, Any]]:
        params = dict(base_params)
        params["start_date"] = _compact_date(start_d)
        params["end_date"] = _compact_date(end_d)
        self.last_holdertrade_meta["requests"] = int(self.last_holdertrade_meta.get("requests") or 0) + 1
        self.last_holdertrade_meta["chunks"] = int(self.last_holdertrade_meta.get("chunks") or 0) + 1
        try:
            return self._query("stk_holdertrade", params, HOLDERTRADE_FIELDS)
        except Exception as exc:  # noqa: BLE001
            self.last_errors.append(
                {
                    "symbol": str(base_params.get("ts_code") or "*"),
                    "error": f"{params['start_date']}~{params['end_date']}: {str(exc)[:240]}",
                }
            )
            return []

    def _query_bars(self, apis: list[str], symbol: str, start: str, end: str) -> list[dict[str, Any]]:
        last_error = None
        saw_success = False
        for api_name in apis:
            if api_name in self._skip_apis:
                continue
            try:
                rows = self._query(api_name, {"ts_code": symbol, "start_date": start, "end_date": end}, DAILY_FIELDS)
                saw_success = True
                if rows:
                    return rows
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if _rate_limit_error(exc):
                    time.sleep(1.6)
                    try:
                        rows = self._query(
                            api_name,
                            {"ts_code": symbol, "start_date": start, "end_date": end},
                            DAILY_FIELDS,
                        )
                        saw_success = True
                        if rows:
                            return rows
                        continue
                    except Exception as retry_exc:  # noqa: BLE001
                        last_error = retry_exc
                        self.last_errors.append({"symbol": symbol, "error": str(retry_exc)[:300]})
                        continue
                if _permission_api_error(exc):
                    self._skip_apis.add(api_name)
                    self.last_errors.append({"symbol": symbol, "error": str(exc)[:300]})
        if last_error and not saw_success:
            raise last_error
        return []

    def _query_factors(self, api_name: str, symbol: str, start: str, end: str) -> dict[str, float | None]:
        if api_name in self._skip_apis:
            return {}
        try:
            rows = self._query(
                api_name,
                {"ts_code": symbol, "start_date": start, "end_date": end},
                "ts_code,trade_date,adj_factor",
            )
            return {_iso_date(row.get("trade_date")): _to_float(row.get("adj_factor")) for row in rows}
        except Exception as exc:  # noqa: BLE001
            self.last_errors.append({"symbol": symbol, "error": str(exc)[:300]})
            if _permission_api_error(exc) or _rate_limit_error(exc):
                self._skip_apis.add(api_name)
            return {}

    def _query(self, api_name: str, params: dict[str, Any], fields: str = "") -> list[dict[str, Any]]:
        payload = self._rest(api_name, params, fields)
        code = payload.get("code")
        if code not in {0, "0", None}:
            raise RuntimeError(f"tushare {api_name} failed: {payload.get('msg') or code}")
        data = payload.get("data") or {}
        names = data.get("fields") or []
        items = data.get("items") or []
        return [dict(zip(names, item)) for item in items]

    def _rest(self, api_name: str, params: dict[str, Any], fields: str = "") -> dict[str, Any]:
        body = json.dumps(
            {"api_name": api_name, "token": self._token_value(), "params": params, "fields": fields}
        ).encode()
        req = urllib.request.Request(
            REST_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return json.loads(_http_read(req, self.timeout))

    def _mcp_call(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        token = self._token_value()
        url = f"{MCP_URL}?token={token}"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            method="POST",
        )
        raw = _http_read(req, self.timeout)
        message = _sse_json(raw)
        if "error" in message:
            raise RuntimeError(str(message["error"]))
        result = message.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(str(result))
        content = result.get("content") or []
        text = content[0].get("text") if content else "[]"
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return []

    def _token_value(self) -> str:
        if self._token:
            return self._token
        token = resolve_tushare_token()
        self._token = token
        return token


def _dedupe_holdertrade_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicates across month/day chunk overlaps."""
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("ts_code") or ""),
            str(row.get("ann_date") or ""),
            str(row.get("holder_name") or ""),
            str(row.get("in_de") or ""),
            str(row.get("change_vol") or ""),
            str(row.get("begin_date") or ""),
            str(row.get("close_date") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def resolve_tushare_token() -> str:
    for key in ("TUSHARE_TOKEN", "TUSHARE_PRO_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    extra = os.environ.get("TUSHARE_TOKEN_FILE", "").strip()
    candidates: list[Path] = []
    if extra:
        candidates.append(Path(extra).expanduser())
    from asqt.config import get_settings

    settings = get_settings()
    candidates.append(settings.data_dir / ".tushare_token")
    for path in candidates:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise RuntimeError("missing Tushare token; set TUSHARE_TOKEN or write data/.tushare_token")


def _permission_api_error(exc: Exception) -> bool:
    text = str(exc)
    return "没有接口" in text or "访问权限" in text


def _rate_limit_error(exc: Exception) -> bool:
    return "频率超限" in str(exc)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _http_read(req: urllib.request.Request, timeout: int) -> str:
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc


def _sse_json(raw: str) -> dict[str, Any]:
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise RuntimeError("tushare MCP returned no JSON payload")


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
