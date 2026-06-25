from typing import Any

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)


def make_engine(prices: dict[str, dict[str, Any]]) -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(prices),
    )


def test_cart_has_a_line_for_an_available_item() -> None:
    engine = make_engine(
        {
            "10295020": {
                "item_id": "10295020",
                "title": "Great Value Paper Towels, 6 Double Rolls",
                "price": 8.97,
                "in_stock": True,
            }
        }
    )

    cart = engine.buildCart(["10295020"])

    assert len(cart.items) == 1
    line = cart.items[0]
    assert line.item_id == "10295020"
    assert line.title == "Great Value Paper Towels, 6 Double Rolls"
    assert line.unit_price == 8.97
    assert line.quantity == 1
    assert line.line_total == 8.97
    assert line.substitution is None
    assert cart.total == 8.97


def test_cart_sums_multiple_items() -> None:
    engine = make_engine(
        {
            "a": {"item_id": "a", "title": "A", "price": 8.97, "in_stock": True},
            "b": {"item_id": "b", "title": "B", "price": 3.50, "in_stock": True},
        }
    )

    cart = engine.buildCart(["a", "b"])

    assert len(cart.items) == 2
    assert cart.total == 12.47


def test_cart_skips_unavailable_items() -> None:
    engine = make_engine(
        {
            "a": {"item_id": "a", "title": "A", "price": 8.97, "in_stock": True},
            "b": {"item_id": "b", "title": "B", "price": 3.50, "in_stock": False},
        }
    )

    cart = engine.buildCart(["a", "b", "unknown"])

    assert [line.item_id for line in cart.items] == ["a"]
    assert cart.total == 8.97


def test_cart_line_surfaces_a_substitution_note() -> None:
    engine = make_engine(
        {
            "a": {
                "item_id": "a",
                "title": "Great Value Paper Towels, 6 Double Rolls",
                "price": 8.97,
                "in_stock": True,
                "substitution": "Bounty 6-pack was unavailable",
            }
        }
    )

    cart = engine.buildCart(["a"])

    assert cart.items[0].substitution == "Bounty 6-pack was unavailable"
