"""Adapter and service protocol boundaries.

External components must stay behind these interfaces so business code does not
depend on Qlib / vendor SDKs / broker private APIs directly.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataSourceAdapter(Protocol):
    """Pull raw market/reference data from an external provider."""

    source_id: str

    def fetch_market_daily(self, symbols: list[str], start: str, end: str) -> list[dict[str, Any]]:
        ...

    def health(self) -> dict[str, Any]:
        ...


@runtime_checkable
class DataNormalizer(Protocol):
    """Convert provider-specific payloads into standard contracts."""

    def normalize_market_daily(self, raw_rows: list[dict[str, Any]], source_id: str) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class QualityChecker(Protocol):
    """Validate standard data before research or trading."""

    def check(self, dataset: str, trade_date: str | None = None) -> dict[str, Any]:
        ...


@runtime_checkable
class ResearchEngine(Protocol):
    """Research / backtest boundary; Qlib stays inside implementations."""

    def run_backtest(self, strategy_id: str, parameter_set_id: str, data_version: str) -> dict[str, Any]:
        ...


@runtime_checkable
class StrategyService(Protocol):
    """Strategy versioning, lifecycle, and target positions."""

    def list_versions(self, strategy_id: str | None = None) -> list[dict[str, Any]]:
        ...

    def generate_target_positions(self, strategy_id: str, trade_date: str) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class OrderService(Protocol):
    """Convert target positions into standard orders with risk checks."""

    def build_orders(self, trade_date: str, strategy_id: str) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class ExecutionAdapter(Protocol):
    """Pluggable execution channel: paper / QMT / vn.py."""

    channel_id: str

    def submit(self, order: dict[str, Any]) -> dict[str, Any]:
        ...

    def cancel(self, order_id: str) -> dict[str, Any]:
        ...

    def query_order(self, order_id: str) -> dict[str, Any]:
        ...

    def channel_status(self) -> dict[str, Any]:
        ...


@runtime_checkable
class ReviewService(Protocol):
    """Attribution, bias analysis, and experiment review."""

    def build_daily_review(self, trade_date: str) -> dict[str, Any]:
        ...


@runtime_checkable
class Scheduler(Protocol):
    """Task orchestration for data / strategy / reporting jobs."""

    def list_tasks(self) -> list[dict[str, Any]]:
        ...

    def run_task(self, task_name: str) -> dict[str, Any]:
        ...


@runtime_checkable
class AlertService(Protocol):
    """Alert creation and notification delivery."""

    def raise_alert(self, level: str, category: str, title: str, detail: str | None = None) -> dict[str, Any]:
        ...


WIRED_PORTS: dict[str, str] = {
    "DataSourceAdapter": "wired",
    "DataNormalizer": "wired",
    "QualityChecker": "wired",
    "ResearchEngine": "wired",
    "StrategyService": "wired",
    "OrderService": "wired",
    "ReviewService": "wired",
    "Scheduler": "wired",
}

PORT_NAMES: tuple[str, ...] = (
    "DataSourceAdapter",
    "DataNormalizer",
    "QualityChecker",
    "ResearchEngine",
    "StrategyService",
    "OrderService",
    "ExecutionAdapter",
    "ReviewService",
    "Scheduler",
    "AlertService",
)


def port_entries() -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "status": WIRED_PORTS.get(name, "not_wired"),
            "phase": "p1" if name in {"DataSourceAdapter", "DataNormalizer", "QualityChecker"} else ("p2" if name in WIRED_PORTS else "later"),
        }
        for name in PORT_NAMES
    ]
