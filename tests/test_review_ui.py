from fastapi.testclient import TestClient

from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.review.render import render_review
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
    FixtureTwilioAdapter,
)
from cartright.shopping_engine.pricing import Cart, CartItem


def fixture_cart() -> Cart:
    return Cart(
        items=[
            CartItem(
                item_id="10295020",
                title="Great Value Paper Towels, 6 Double Rolls",
                unit_price=8.97,
                quantity=1,
                line_total=8.97,
                substitution=None,
            ),
            CartItem(
                item_id="37774610",
                title="Folgers Classic Roast Ground Coffee, 25.9 oz",
                unit_price=6.50,
                quantity=1,
                line_total=6.50,
                substitution="Maxwell House was unavailable",
            ),
        ],
        total=15.47,
    )


def test_review_renders_items_prices_and_total() -> None:
    html = render_review(fixture_cart())

    assert "Great Value Paper Towels, 6 Double Rolls" in html
    assert "Folgers Classic Roast Ground Coffee, 25.9 oz" in html
    assert "$8.97" in html
    assert "$6.50" in html
    assert "$15.47" in html  # total


def test_review_renders_substitution_note() -> None:
    html = render_review(fixture_cart())

    assert "Maxwell House was unavailable" in html


def test_review_has_a_single_cta_link() -> None:
    html = render_review(fixture_cart(), cta_url="https://example.test/cart")

    assert html.count("Open in my Walmart cart") == 1
    assert 'href="https://example.test/cart"' in html


def test_review_handles_an_empty_cart() -> None:
    html = render_review(Cart(items=[], total=0.0))

    assert "Nothing available to review" in html
    # No CTA when there's nothing to buy.
    assert "Open in my Walmart cart" not in html


class _FakeParser:
    def parse(self, text: str) -> ParsedPreference:  # pragma: no cover - unused here
        raise AssertionError("parser should not be called by the review route")


def test_review_route_renders_a_real_built_cart() -> None:
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(
            {
                "10295020": {
                    "item_id": "10295020",
                    "title": "Great Value Paper Towels, 6 Double Rolls",
                    "price": 8.97,
                    "in_stock": True,
                }
            }
        ),
    )
    client = TestClient(
        create_app(
            parser=_FakeParser(),
            engine=engine,
            twilio=FixtureTwilioAdapter(),
            user_number="+15555550123",
        )
    )

    response = client.get("/review", params={"item": "10295020"})

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Great Value Paper Towels, 6 Double Rolls" in response.text
    assert "$8.97" in response.text
