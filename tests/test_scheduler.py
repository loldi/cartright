from __future__ import annotations

from datetime import date
from typing import Any

from cartright.scheduler import run_alert_cycle
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import CatalogPricingAdapter
from cartright.shopping_engine.adapters.fixtures import (
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)
from cartright.shopping_engine.engine import ReorderCandidate
from cartright.shopping_engine.pricing import DealEvaluation

PAPER_TOWELS = "10295020"
COFFEE = "37774610"
TODAY = date(2026, 6, 21)

# Paper towels: ordered 2026-06-01 and 2026-06-11 (10-day gap) -> predicted
# window [2026-06-20, 2026-06-22], which contains TODAY.
# Coffee: ordered 2026-05-01 and 2026-05-08 (7-day gap) -> predicted window
# [2026-05-14, 2026-05-16], well before TODAY.
ORDERS = [
    {
        "item_id": PAPER_TOWELS,
        "title": "Great Value Paper Towels, 6 Double Rolls",
        "ordered_at": "2026-06-01",
    },
    {
        "item_id": PAPER_TOWELS,
        "title": "Great Value Paper Towels, 6 Double Rolls",
        "ordered_at": "2026-06-11",
    },
    {
        "item_id": COFFEE,
        "title": "Folgers Classic Roast Ground Coffee, 25.9 oz",
        "ordered_at": "2026-05-01",
    },
    {
        "item_id": COFFEE,
        "title": "Folgers Classic Roast Ground Coffee, 25.9 oz",
        "ordered_at": "2026-05-08",
    },
]


class _SpyCatalog(CatalogPricingAdapter):
    """Records every item_id it's asked to price, so tests can assert which
    candidates actually got deal-checked."""

    def __init__(self, prices: dict[str, dict[str, Any]]) -> None:
        self._prices = prices
        self.queried: list[str] = []

    def get_price(self, item_id: str) -> dict[str, Any]:
        self.queried.append(item_id)
        return self._prices.get(item_id, {})


class _FakeComposer:
    """Stand-in for the LLM: returns canned text, records what it was given."""

    def __init__(self, body: str = "Deal alert!") -> None:
        self._body = body
        self.calls: list[tuple[ReorderCandidate, DealEvaluation, str]] = []

    def compose(self, candidate: ReorderCandidate, deal: DealEvaluation, review_url: str) -> str:
        self.calls.append((candidate, deal, review_url))
        return self._body


def make_engine(catalog: CatalogPricingAdapter) -> ShoppingEngine:
    return ShoppingEngine(order_history=FixtureOrderHistoryAdapter(ORDERS), catalog=catalog)


def test_out_of_window_candidate_is_never_deal_checked_or_alerted() -> None:
    catalog = _SpyCatalog(
        {
            PAPER_TOWELS: {"price": 8.97, "was_price": 10.97, "in_stock": True},
            COFFEE: {"price": 5.00, "was_price": 7.00, "in_stock": True},
        }
    )
    engine = make_engine(catalog)
    composer = _FakeComposer()
    messenger = FixtureMessenger()

    run_alert_cycle(
        engine=engine,
        composer=composer,
        messenger=messenger,
        user_chat_id="987654321",
        review_base_url="https://example.test/review",
        today=TODAY,
    )

    # Coffee is outside its window today - it must never even reach evaluateDeal.
    assert COFFEE not in catalog.queried


def test_in_window_deal_triggers_one_alert_linking_to_the_review_page() -> None:
    catalog = _SpyCatalog(
        {
            PAPER_TOWELS: {"price": 8.97, "was_price": 10.97, "in_stock": True},
            COFFEE: {"price": 5.00, "was_price": 7.00, "in_stock": True},
        }
    )
    engine = make_engine(catalog)
    composer = _FakeComposer(body="Paper towels are 18% off - check it out!")
    messenger = FixtureMessenger()

    sent = run_alert_cycle(
        engine=engine,
        composer=composer,
        messenger=messenger,
        user_chat_id="987654321",
        review_base_url="https://example.test/review",
        today=TODAY,
    )

    assert sent == ["Paper towels are 18% off - check it out!"]
    assert len(composer.calls) == 1
    candidate, deal, review_url = composer.calls[0]
    assert candidate.item_id == PAPER_TOWELS
    assert deal.is_deal is True
    assert review_url == f"https://example.test/review?item={PAPER_TOWELS}"
    assert messenger.sent == [
        {"to": "987654321", "body": "Paper towels are 18% off - check it out!"}
    ]


def test_no_alert_when_in_window_but_no_real_deal() -> None:
    catalog = _SpyCatalog(
        {
            PAPER_TOWELS: {"price": 10.97, "in_stock": True},  # full price, no was_price
            COFFEE: {"price": 5.00, "was_price": 7.00, "in_stock": True},
        }
    )
    engine = make_engine(catalog)
    composer = _FakeComposer()
    messenger = FixtureMessenger()

    sent = run_alert_cycle(
        engine=engine,
        composer=composer,
        messenger=messenger,
        user_chat_id="987654321",
        review_base_url="https://example.test/review",
        today=TODAY,
    )

    assert sent == []
    assert composer.calls == []
    assert messenger.sent == []
    # It WAS checked (it's in-window) - just turned out not to be a real deal.
    assert PAPER_TOWELS in catalog.queried
