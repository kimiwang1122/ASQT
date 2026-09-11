"""Mock OrderService: quality gate on new orders without a live broker."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from asqt.config import Settings, get_settings
from asqt.db import execute, query_all
from asqt.ops import quality_gate
from asqt.storage import read_market_snapshot


class MockOrderService:
    """Writes standard_order rows. Rejects when open quality issues are `block`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def quality_gate(self) -> dict:
        return quality_gate(self.settings)

    def list_orders(self, limit: int = 20) -> list[dict]:
        return query_all(
            "SELECT * FROM standard_order ORDER BY created_at DESC LIMIT ?",
            (limit,),
            settings=self.settings,
        )

    def place_mock(
        self,
        *,
        symbol: str,
        side: str = "BUY",
        quantity: int = 100,
        trade_date: str | None = None,
        strategy_id: str = "mock_p1",
    ) -> dict:
        symbol = (symbol or "").strip().upper()
        side = (side or "BUY").upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if "." not in symbol:
            raise ValueError("symbol must look like 000001.SZ")

        asof = trade_date or read_market_snapshot(limit=1, settings=self.settings).get("trade_date")
        if not asof:
            asof = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        gate = self.quality_gate()
        idem_key = f"{strategy_id}|{asof}|{symbol}|{side}|mock"
        existing = query_all(
            "SELECT * FROM standard_order WHERE idem_key = ?",
            (idem_key,),
            settings=self.settings,
        )
        if existing:
            row = existing[0]
            return {
                "accepted": row["status"] != "rejected",
                "duplicate": True,
                "quality": gate,
                "order": row,
            }

        status = "risk_pending" if gate["trade_allowed"] else "rejected"
        order_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        execute(
            """
            INSERT INTO standard_order
                (order_id, idem_key, trade_date, strategy_id, symbol, side, quantity,
                 price_type, limit_price, valid_date, risk_tags, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'limit', NULL, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                idem_key,
                asof,
                strategy_id,
                symbol,
                side,
                quantity,
                asof,
                "quality_block" if status == "rejected" else "mock",
                status,
                now,
                now,
            ),
            settings=self.settings,
        )
        order = query_all(
            "SELECT * FROM standard_order WHERE order_id = ?",
            (order_id,),
            settings=self.settings,
        )[0]
        return {
            "accepted": status != "rejected",
            "duplicate": False,
            "quality": gate,
            "order": order,
            "reason": None if status != "rejected" else "quality_block",
        }

    def build_orders(self, trade_date: str, strategy_id: str) -> list[dict]:
        result = self.place_mock(symbol="000001.SZ", trade_date=trade_date, strategy_id=strategy_id)
        return [result["order"]]
