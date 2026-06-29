from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DealAlert:
    """One real, already-confirmed deal worth telling the user about.

    Every field here is already-real `ShoppingEngine`/catalog output - the
    composer only ever rephrases these facts, never invents or rounds one of
    its own. `last_paid_price` is `None` when no order history has a price on
    it (rare, but tolerated rather than crashing the alert cycle).
    """

    item_id: str
    title: str
    product_url: str | None
    current_price: float
    last_paid_price: float | None
    savings: float
    window_start: str
    window_end: str


class AlertComposer(Protocol):
    """Turns one or more already-evaluated, real deals into one proactive
    Telegram alert.

    The production implementation drives this with a live Claude completion
    constrained to the real facts handed in; tests supply a fake that returns
    canned text, so no real LLM call ever happens in the test path. Always
    composes exactly one message body - the cart-add link/button is a
    deterministic, non-LLM concern the scheduler attaches separately.
    """

    def compose(self, deals: list[DealAlert]) -> str: ...
