"""Guardrail for the PRD's hardest non-negotiable: approve-then-handoff only.

Nothing in this codebase may ever submit a real Walmart order on its own.
These tests assert that property structurally rather than by exercising one
code path, so a future change can't quietly reintroduce an auto-submit.
"""

import re
from pathlib import Path

from cartright.review.render import render_review
from cartright.shopping_engine.adapters.base import CatalogPricingAdapter
from cartright.shopping_engine.engine import ShoppingEngine
from cartright.shopping_engine.pricing import Cart, CartItem, build_walmart_cart_url

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "cartright"

# Any of these appearing in source would indicate a code path that completes
# a purchase rather than merely linking the user to their own cart.
_FORBIDDEN_PATTERNS = [
    r"submit[_-]?order",
    r"place[_-]?order",
    r"complete[_-]?purchase",
    r"checkout.{0,20}submit",
    r"submit.{0,20}checkout",
    r"auto[_-]?submit",
    r"auto[_-]?purchase",
    r"auto[_-]?checkout",
]


def test_no_source_file_contains_an_order_submission_code_path() -> None:
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text()
        for pattern in _FORBIDDEN_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(SRC_ROOT)}: matched /{pattern}/")
    assert not offenders, "Found a code path that looks like it submits an order:\n" + "\n".join(
        offenders
    )


def test_catalog_pricing_adapter_interface_is_read_only() -> None:
    # buildCart()'s only seam into "Walmart" is this adapter. As long as its
    # interface exposes nothing beyond reading a price, no implementation
    # behind ShoppingEngine has a way to submit a purchase.
    assert CatalogPricingAdapter.__abstractmethods__ == frozenset({"get_price"})


def test_shopping_engine_exposes_no_order_submission_method() -> None:
    public_methods = {name for name in dir(ShoppingEngine) if not name.startswith("_")}
    forbidden = {"submitOrder", "placeOrder", "completePurchase", "checkout", "buy"}
    assert public_methods.isdisjoint(forbidden)


def test_walmart_cart_url_is_a_plain_string_no_request_is_made() -> None:
    # Building the CTA link must be pure string assembly - if it were a
    # network call, that would itself be a step toward an unattended action.
    cart = Cart(items=[CartItem("1", "Item", 1.0, 1, 1.0, None)], total=1.0)
    url = build_walmart_cart_url(cart)
    assert isinstance(url, str)
    assert url.startswith("https://affil.walmart.com/cart/addToCart")


def test_review_page_cta_is_the_only_way_to_proceed_and_never_auto_redirects() -> None:
    cart = Cart(items=[CartItem("1", "Item", 1.0, 1, 1.0, None)], total=1.0)
    html = render_review(cart)
    # A single anchor the user must tap; no meta-refresh, no client-side
    # auto-navigation, no form that could submit anything on page load.
    assert '<meta http-equiv="refresh"' not in html.lower()
    assert "<form" not in html.lower()
    assert "window.location" not in html
    assert html.count('class="mt-8 block w-full rounded-lg bg-blue-600') == 1
