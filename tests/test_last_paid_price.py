from __future__ import annotations

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)

PAPER_TOWELS = "10295020"


def make_engine(orders: list[dict[str, object]]) -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(orders),
        catalog=FixtureCatalogPricingAdapter(),
    )


def test_returns_the_most_recent_orders_price() -> None:
    engine = make_engine(
        [
            {
                "item_id": PAPER_TOWELS,
                "title": "Paper Towels",
                "ordered_at": "2026-06-01",
                "price": 10.97,
            },
            {
                "item_id": PAPER_TOWELS,
                "title": "Paper Towels",
                "ordered_at": "2026-06-11",
                "price": 9.50,
            },
        ]
    )

    assert engine.lastPaidPrice(PAPER_TOWELS) == 9.50


def test_none_when_no_order_history_for_the_item() -> None:
    engine = make_engine([])

    assert engine.lastPaidPrice(PAPER_TOWELS) is None


def test_none_when_the_latest_order_has_no_price_field() -> None:
    engine = make_engine(
        [{"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-01"}]
    )

    assert engine.lastPaidPrice(PAPER_TOWELS) is None
