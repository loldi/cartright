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


def test_discounted_in_stock_item_is_a_deal() -> None:
    engine = make_engine(
        {
            "10295020": {
                "item_id": "10295020",
                "title": "Great Value Paper Towels, 6 Double Rolls",
                "price": 8.97,
                "was_price": 10.97,
                "in_stock": True,
            }
        }
    )

    result = engine.evaluateDeal("10295020")

    assert result.item_id == "10295020"
    assert result.is_deal is True
    assert result.current_price == 8.97
    assert result.reference_price == 10.97
    assert result.savings == 2.00


def test_item_at_full_price_is_not_a_deal() -> None:
    engine = make_engine(
        {"x": {"item_id": "x", "price": 10.97, "was_price": 10.97, "in_stock": True}}
    )

    result = engine.evaluateDeal("x")

    assert result.is_deal is False
    assert result.current_price == 10.97
    assert result.savings == 0.0


def test_discount_below_threshold_is_not_a_deal() -> None:
    # 5% off: real but too small to surface (degrades the relationship).
    engine = make_engine(
        {"x": {"item_id": "x", "price": 9.50, "was_price": 10.00, "in_stock": True}}
    )

    assert engine.evaluateDeal("x").is_deal is False


def test_out_of_stock_item_is_not_a_deal() -> None:
    engine = make_engine(
        {"x": {"item_id": "x", "price": 5.00, "was_price": 10.00, "in_stock": False}}
    )

    result = engine.evaluateDeal("x")

    assert result.is_deal is False
    assert result.current_price is None


def test_unknown_item_is_not_a_deal() -> None:
    engine = make_engine({})

    result = engine.evaluateDeal("nope")

    assert result.is_deal is False
    assert result.current_price is None


def test_item_without_reference_price_is_not_a_deal() -> None:
    engine = make_engine({"x": {"item_id": "x", "price": 5.00, "in_stock": True}})

    result = engine.evaluateDeal("x")

    assert result.is_deal is False
    assert result.current_price == 5.00
    assert result.reference_price is None


def test_product_url_is_carried_through_when_the_catalog_has_one() -> None:
    engine = make_engine(
        {
            "10295020": {
                "item_id": "10295020",
                "price": 8.97,
                "was_price": 10.97,
                "in_stock": True,
                "product_url": "https://www.walmart.com/ip/Great-Value-Paper-Towels/10295020",
            }
        }
    )

    result = engine.evaluateDeal("10295020")

    assert result.product_url == "https://www.walmart.com/ip/Great-Value-Paper-Towels/10295020"


def test_product_url_is_none_when_the_catalog_has_none() -> None:
    engine = make_engine(
        {"10295020": {"item_id": "10295020", "price": 8.97, "was_price": 10.97, "in_stock": True}}
    )

    assert engine.evaluateDeal("10295020").product_url is None
