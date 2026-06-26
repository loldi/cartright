"""Slice 6: prove the system tracks 2+ unrelated items independently, end to end.

getReorderCandidates(), the scheduler, recordPreference()/getPreference(), and
buildCart() were all built generically against item_id from earlier slices -
this slice's job is to prove that genericity holds across the whole pipeline
at once, with no state leaking between unrelated tracked items, rather than
leaving it only implicitly true.
"""

from datetime import date
from typing import Any

from cartright.scheduler import run_alert_cycle
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import CatalogPricingAdapter
from cartright.shopping_engine.adapters.fixtures import (
    FixtureOrderHistoryAdapter,
    FixtureTwilioAdapter,
)
from cartright.shopping_engine.engine import ReorderCandidate
from cartright.shopping_engine.pricing import DealEvaluation

PAPER_TOWELS = "10295020"
COFFEE = "37774610"
DISH_SOAP = "44556677"
TODAY = date(2026, 6, 21)

ORDERS = [
    # paper towels: 10-day cadence -> window [2026-06-20, 2026-06-22], contains TODAY
    {"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-01"},
    {"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-11"},
    # coffee: also 10-day cadence but offset, window [2026-06-21, 2026-06-23] - also contains TODAY
    {"item_id": COFFEE, "title": "Coffee", "ordered_at": "2026-06-02"},
    {"item_id": COFFEE, "title": "Coffee", "ordered_at": "2026-06-12"},
    # dish soap: far in the past, well outside its window today
    {"item_id": DISH_SOAP, "title": "Dish Soap", "ordered_at": "2026-01-01"},
    {"item_id": DISH_SOAP, "title": "Dish Soap", "ordered_at": "2026-01-11"},
]


class _SpyCatalog(CatalogPricingAdapter):
    """Records every item_id it's asked to price, so a test can prove an
    out-of-window item is never even queried, not just unalerted."""

    def __init__(self, prices: dict[str, dict[str, Any]]) -> None:
        self._prices = prices
        self.queried: list[str] = []

    def get_price(self, item_id: str) -> dict[str, Any]:
        self.queried.append(item_id)
        return self._prices.get(item_id, {})


class _RecordingComposer:
    def __init__(self) -> None:
        self.calls: list[tuple[ReorderCandidate, DealEvaluation, str]] = []

    def compose(self, candidate: ReorderCandidate, deal: DealEvaluation, review_url: str) -> str:
        self.calls.append((candidate, deal, review_url))
        return f"Deal on {candidate.title}: {review_url}"


def make_engine(catalog: CatalogPricingAdapter) -> ShoppingEngine:
    return ShoppingEngine(order_history=FixtureOrderHistoryAdapter(ORDERS), catalog=catalog)


def test_get_reorder_candidates_returns_independent_windows_for_three_unrelated_items() -> None:
    engine = make_engine(_SpyCatalog({}))

    candidates = {c.item_id: c for c in engine.getReorderCandidates()}

    assert set(candidates) == {PAPER_TOWELS, COFFEE, DISH_SOAP}
    assert candidates[PAPER_TOWELS].window_start == "2026-06-20"
    assert candidates[COFFEE].window_start == "2026-06-21"
    assert candidates[DISH_SOAP].window_start == "2026-01-20"


def test_scheduler_alerts_independently_for_each_in_window_item_without_cross_suppression() -> None:
    catalog = _SpyCatalog(
        {
            PAPER_TOWELS: {"price": 8.97, "was_price": 10.97, "in_stock": True},
            COFFEE: {"price": 5.00, "was_price": 7.00, "in_stock": True},
            # Dish soap would also read as a real deal if it were ever checked -
            # the point is that being outside its window means it never is.
            DISH_SOAP: {"price": 3.00, "was_price": 6.00, "in_stock": True},
        }
    )
    engine = make_engine(catalog)
    composer = _RecordingComposer()
    twilio = FixtureTwilioAdapter()

    sent = run_alert_cycle(
        engine=engine,
        composer=composer,
        twilio=twilio,
        user_number="+15555550123",
        review_base_url="https://example.test/review",
        today=TODAY,
    )

    assert len(sent) == 2
    alerted_items = {call[0].item_id for call in composer.calls}
    assert alerted_items == {PAPER_TOWELS, COFFEE}
    assert len(twilio.sent) == 2
    assert DISH_SOAP not in catalog.queried
    assert PAPER_TOWELS in catalog.queried
    assert COFFEE in catalog.queried


def test_preferences_on_different_items_never_leak_into_each_other() -> None:
    engine = make_engine(_SpyCatalog({}))

    engine.recordPreference(PAPER_TOWELS, {"brand": "Bounty"}, source="explicit")
    engine.recordPreference(COFFEE, {"brand": "Folgers"}, source="inferred")
    # An inferred preference on dish soap, recorded after an *explicit* one on
    # paper towels, must not be blocked by paper towels' precedence - explicit
    # precedence is tracked per item_id, not as a single global flag.
    engine.recordPreference(DISH_SOAP, {"brand": "Dawn"}, source="inferred")

    towels = engine.getPreference(PAPER_TOWELS)
    coffee = engine.getPreference(COFFEE)
    soap = engine.getPreference(DISH_SOAP)

    assert towels is not None
    assert towels.attributes == {"brand": "Bounty"}
    assert towels.source == "explicit"
    assert coffee is not None
    assert coffee.attributes == {"brand": "Folgers"}
    assert coffee.source == "inferred"
    assert soap is not None
    assert soap.attributes == {"brand": "Dawn"}
    assert soap.source == "inferred"


def test_cart_spans_multiple_independently_tracked_items() -> None:
    engine = make_engine(
        _SpyCatalog(
            {
                PAPER_TOWELS: {"title": "Paper Towels", "price": 8.97, "in_stock": True},
                COFFEE: {"title": "Coffee", "price": 6.50, "in_stock": True},
            }
        )
    )

    cart = engine.buildCart([PAPER_TOWELS, COFFEE])

    assert {line.item_id for line in cart.items} == {PAPER_TOWELS, COFFEE}
    assert cart.total == round(8.97 + 6.50, 2)
