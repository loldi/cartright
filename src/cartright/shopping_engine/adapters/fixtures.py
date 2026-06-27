from __future__ import annotations

from typing import Any

from cartright.shopping_engine.adapters.base import (
    CatalogPricingAdapter,
    Messenger,
    OrderHistoryAdapter,
)


class FixtureOrderHistoryAdapter(OrderHistoryAdapter):
    def __init__(self, orders: list[dict[str, Any]] | None = None) -> None:
        self._orders = orders or []

    def get_orders(self, item_id: str | None = None) -> list[dict[str, Any]]:
        if item_id is None:
            return list(self._orders)
        return [order for order in self._orders if order.get("item_id") == item_id]


class FixtureCatalogPricingAdapter(CatalogPricingAdapter):
    def __init__(self, prices: dict[str, dict[str, Any]] | None = None) -> None:
        self._prices = prices or {}

    def get_price(self, item_id: str) -> dict[str, Any]:
        return self._prices.get(item_id, {})


class FixtureMessenger(Messenger):
    """In-memory Messenger stand-in: records every message sent, for assertions."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send_message(self, to: str, body: str) -> None:
        self.sent.append({"to": to, "body": body})
