from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OrderHistoryAdapter(ABC):
    """Reads structured past-order data for the single user this project serves.

    Implementations have no knowledge of how that data was produced (e.g. the
    private self-scrape utility excluded from this repo) - they only consume
    its already-structured output.
    """

    @abstractmethod
    def get_orders(self, item_id: str | None = None) -> list[dict[str, Any]]: ...


class CatalogPricingAdapter(ABC):
    """Reads current price/availability for a catalog item.

    The production implementation is built exclusively against publicly
    documented Walmart APIs.
    """

    @abstractmethod
    def get_price(self, item_id: str) -> dict[str, Any]: ...


class Messenger(ABC):
    """Sends a text message to the single private recipient this project serves.

    Transport-agnostic on purpose: the engine, scheduler, and conversation layer
    only need "send some text to a recipient handle". The concrete adapter
    (Telegram today) owns the wire details. Inbound is push-based (a webhook),
    so there is no receive method here - the web layer hands inbound text
    straight to `handle_inbound_preference`.
    """

    @abstractmethod
    def send_message(self, to: str, body: str) -> None: ...
