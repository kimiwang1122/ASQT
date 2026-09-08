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
