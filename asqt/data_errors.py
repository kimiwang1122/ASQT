"""Market data availability errors (no data / stale asof)."""

from __future__ import annotations

from typing import Any


class DataAvailabilityError(Exception):
    """Base for missing or unusable market data."""

    code = "data_unavailable"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.details}


class NoMarketDataError(DataAvailabilityError):
    """No usable bars for the requested asof / symbol set."""

    code = "no_market_data"


class StaleDataError(DataAvailabilityError):
    """Latest bar is older than asof by more than N trading sessions."""

    code = "stale_data"

    def __init__(
        self,
        message: str,
        *,
        asof: str,
        latest: str | None = None,
        lag_sessions: int | None = None,
        max_lag: int | None = None,
        symbol: str | None = None,
    ) -> None:
        details = {
            "asof": asof,
            "latest": latest,
            "lag_sessions": lag_sessions,
            "max_lag": max_lag,
            "symbol": symbol,
        }
        super().__init__(message, details={k: v for k, v in details.items() if v is not None})
        self.asof = asof
        self.latest = latest
        self.lag_sessions = lag_sessions
        self.max_lag = max_lag
        self.symbol = symbol
