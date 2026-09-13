from __future__ import annotations

from asqt.adapters.tushare_source import TushareAdapter
from asqt.normalize import StandardNormalizer


class FakeTushare(TushareAdapter):
    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.throttle_s = 0
        self.calls: list[tuple[str, dict]] = []

    def _query(self, api_name: str, params: dict, fields: str = ""):
        self.calls.append((api_name, params))
        if api_name == "daily":
            return [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260907",
                    "open": 11.87,
                    "high": 11.88,
                    "low": 11.65,
                    "close": 11.7,
                    "pre_close": 11.89,
                    "vol": 100.0,
                    "amount": 12.5,
                }
            ]
        if api_name == "adj_factor":
            return [{"ts_code": "000001.SZ", "trade_date": "20260907", "adj_factor": 132.5}]
        if api_name == "stock_basic":
            return [{"ts_code": "000001.SZ", "name": "平安银行", "list_date": "19910403", "delist_date": None}]
        if api_name == "fund_daily":
            return [
                {
                    "ts_code": "510050.SH",
                    "trade_date": "20260907",
                    "open": 3.0,
                    "high": 3.1,
                    "low": 2.9,
                    "close": 3.05,
                    "pre_close": 3.0,
                    "vol": 10.0,
                    "amount": 3.0,
                }
            ]
        if api_name == "fund_adj":
            return [{"ts_code": "510050.SH", "trade_date": "20260907", "adj_factor": 1.2}]
        if api_name == "fund_basic":
            return [{"ts_code": "510050.SH", "name": "50ETF", "list_date": "20040223", "delist_date": None}]
        return []


def test_tushare_packs_stock_and_etf_units():
    adapter = FakeTushare()
    rows = adapter.fetch_market_daily(["000001.SZ", "510050.SH"], "2026-09-01", "2026-09-07")
    stock = next(row for row in rows if row["symbol"] == "000001.SZ")
    etf = next(row for row in rows if row["symbol"] == "510050.SH")
    assert stock["date"] == "2026-09-07"
    assert stock["volume"] == 10000
    assert stock["amount"] == 12500.0
    assert stock["adj_factor"] == 132.5
    assert etf["volume"] == 1000
    assert etf["adj_factor"] == 1.2
    apis = [name for name, _ in adapter.calls]
    assert "daily" in apis and "fund_daily" in apis
    normalized = StandardNormalizer().normalize_market_daily(rows, "tushare")
    assert normalized[0]["source"] == "tushare"
    assert normalized[0]["trade_date"] == "2026-09-07"


def test_iter_month_and_day_windows():
    from datetime import date

    from asqt.adapters.tushare_source import iter_day_windows, iter_month_windows

    months = iter_month_windows(date(2024, 1, 15), date(2024, 3, 5))
    assert months == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 5)),
    ]
    days = iter_day_windows(date(2024, 1, 30), date(2024, 2, 1))
    assert days == [
        (date(2024, 1, 30), date(2024, 1, 30)),
        (date(2024, 1, 31), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 1)),
    ]


def test_fetch_stk_holdertrade_pages_by_month_and_day_when_capped():
    from asqt.adapters.tushare_source import STK_HOLDERTRADE_MAX_ROWS, TushareAdapter

    class PagingFake(TushareAdapter):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.throttle_s = 0
            self.calls: list[tuple[str, str]] = []

        def _query(self, api_name: str, params: dict, fields: str = ""):
            assert api_name == "stk_holdertrade"
            start = params["start_date"]
            end = params["end_date"]
            self.calls.append((start, end))
            # Whole January returns a full page → must subdivide by day.
            if start == "20240101" and end == "20240131":
                return [
                    {
                        "ts_code": f"{i:06d}.SZ",
                        "ann_date": "20240115",
                        "holder_name": f"H{i}",
                        "in_de": "IN",
                        "change_vol": i,
                    }
                    for i in range(STK_HOLDERTRADE_MAX_ROWS)
                ]
            # Single-day responses stay under the cap.
            return [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": start,
                    "holder_name": "Day Holder",
                    "in_de": "DE",
                    "change_vol": 1,
                }
            ]

    adapter = PagingFake()
    rows = adapter.fetch_stk_holdertrade(start="2024-01-01", end="2024-01-31")
    assert ("20240101", "20240131") in adapter.calls
    # After hitting the month cap, each day in January is requested.
    assert ("20240101", "20240101") in adapter.calls
    assert ("20240131", "20240131") in adapter.calls
    assert adapter.last_holdertrade_meta["requests"] == 1 + 31
    assert adapter.last_holdertrade_meta["chunk_hits_limit"]
    # Month payload is discarded and replaced by day slices.
    assert len(rows) == 31
    assert adapter.last_holdertrade_meta["fetched_deduped"] == 31
    assert {row["ann_date"] for row in rows} == {f"202401{i:02d}" for i in range(1, 32)}


def test_fetch_stk_holdertrade_defaults_range_and_multi_month():
    from datetime import date, timedelta

    from asqt.adapters.tushare_source import DEFAULT_HOLDERTRADE_LOOKBACK_DAYS, TushareAdapter

    class RangeFake(TushareAdapter):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.throttle_s = 0
            self.calls: list[tuple[str, str]] = []

        def _query(self, api_name: str, params: dict, fields: str = ""):
            self.calls.append((params["start_date"], params["end_date"]))
            return [
                {
                    "ts_code": "600000.SH",
                    "ann_date": params["start_date"],
                    "holder_name": "X",
                    "in_de": "IN",
                    "change_vol": 10,
                }
            ]

    adapter = RangeFake()
    rows = adapter.fetch_stk_holdertrade(start="2024-02-10", end="2024-04-02")
    assert adapter.calls[0] == ("20240210", "20240229")
    assert adapter.calls[1] == ("20240301", "20240331")
    assert adapter.calls[2] == ("20240401", "20240402")
    assert len(rows) == 3
    assert adapter.last_holdertrade_meta["start"] == "2024-02-10"
    assert adapter.last_holdertrade_meta["end"] == "2024-04-02"

    defaulted = RangeFake()
    defaulted.fetch_stk_holdertrade()
    expected_start = (date.today() - timedelta(days=DEFAULT_HOLDERTRADE_LOOKBACK_DAYS)).isoformat()
    assert defaulted.last_holdertrade_meta["start"] == expected_start
    assert defaulted.last_holdertrade_meta["default_lookback_days"] == DEFAULT_HOLDERTRADE_LOOKBACK_DAYS
    assert defaulted.last_holdertrade_meta["requests"] >= 12
