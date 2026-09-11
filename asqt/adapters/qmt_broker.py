"""QMT / XtQuant execution adapter placeholder.

Q2 is still open: no live MiniQMT session in this environment.
This module must stay vendor-SDK-free until credentials exist.
Business code continues to use PaperBroker.
"""

from __future__ import annotations

from typing import Any


class QmtExecutionAdapter:
    channel_id = "qmt"

    def channel_status(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "available": False,
            "reason": "q2_pending",
            "detail": "QMT/XtQuant 未接入；等模拟盘权限后再接线。当前执行通道仍是 PaperBroker。",
        }

    def submit(self, order: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("QMT not configured (Q2 pending); use PaperBroker")

    def cancel(self, order_id: str) -> dict[str, Any]:
        raise RuntimeError("QMT not configured (Q2 pending); use PaperBroker")

    def query_order(self, order_id: str) -> dict[str, Any]:
        raise RuntimeError("QMT not configured (Q2 pending); use PaperBroker")
