from __future__ import annotations

from abc import ABC, abstractmethod


class OrderHistoryAdapter(ABC):
    """Reads structured past-order data for the single user this project serves.

    Implementations have no knowledge of how that data was produced (e.g. the
    private self-scrape utility excluded from this repo) - they only consume
    its already-structured output.
    """

    @abstractmethod
    def get_orders(self, item_id: str | None = None) -> list[dict]:
        ...


class CatalogPricingAdapter(ABC):
    """Reads current price/availability for a catalog item.

    The production implementation is built exclusively against publicly
    documented Walmart APIs.
    """

    @abstractmethod
    def get_price(self, item_id: str) -> dict:
        ...


class TwilioAdapter(ABC):
    """Sends and receives SMS for the single private number this project uses."""

    @abstractmethod
    def send_sms(self, to: str, body: str) -> None:
        ...

    @abstractmethod
    def receive_sms(self) -> list[dict]:
        ...
