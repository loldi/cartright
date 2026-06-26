from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Minimum discount off the reference price for a price drop to count as a deal
# worth surfacing. Below this we stay quiet rather than degrade the relationship
# by texting about marginal "deals".
DEAL_MIN_DISCOUNT = 0.10


@dataclass(frozen=True)
class DealEvaluation:
    item_id: str
    is_deal: bool
    current_price: float | None
    reference_price: float | None
    savings: float


def evaluate_deal(item_id: str, price: dict[str, Any]) -> DealEvaluation:
    """Decide whether an item's current price is a real, surfaceable deal.

    Grounded entirely in the catalog's price data: the item must be in stock,
    have a reference (`was_price`) to discount from, and be marked down by at
    least `DEAL_MIN_DISCOUNT`. Anything else is not a deal.
    """
    if not price or not price.get("in_stock", False):
        return DealEvaluation(item_id, False, None, None, 0.0)

    current = float(price["price"])
    reference_raw = price.get("was_price")
    if reference_raw is None:
        return DealEvaluation(item_id, False, current, None, 0.0)

    reference = float(reference_raw)
    discount = (reference - current) / reference if reference > 0 else 0.0
    is_deal = current < reference and discount >= DEAL_MIN_DISCOUNT
    savings = round(reference - current, 2) if is_deal else 0.0
    return DealEvaluation(item_id, is_deal, current, reference, savings)


@dataclass(frozen=True)
class CartItem:
    item_id: str
    title: str
    unit_price: float
    quantity: int
    line_total: float
    substitution: str | None


@dataclass(frozen=True)
class Cart:
    items: list[CartItem]
    total: float


def build_cart(item_ids: list[str], get_price: Callable[[str], dict[str, Any]]) -> Cart:
    """Assemble an itemized cart from current catalog prices.

    Only in-stock, priceable items make it into the cart - you can't put
    something unavailable in front of the user as ready to buy. A line may
    carry a substitution note when the catalog returned a substitute product.
    """
    items: list[CartItem] = []
    total = 0.0
    for item_id in item_ids:
        price = get_price(item_id)
        if not price or not price.get("in_stock", False):
            continue
        unit_price = float(price["price"])
        quantity = 1
        line_total = round(unit_price * quantity, 2)
        items.append(
            CartItem(
                item_id=item_id,
                title=price.get("title", item_id),
                unit_price=unit_price,
                quantity=quantity,
                line_total=line_total,
                substitution=price.get("substitution"),
            )
        )
        total += line_total
    return Cart(items=items, total=round(total, 2))


# Walmart's publicly documented affiliate "Add to Cart" deep link: it stages
# the given items directly into the *user's own* walmart.com cart for them to
# complete manually. Building this string performs no request of any kind -
# nothing in this codebase ever follows it on the user's behalf.
WALMART_ADD_TO_CART_URL = "https://affil.walmart.com/cart/addToCart"


def build_walmart_cart_url(cart: Cart) -> str:
    """Build a real walmart.com cart deep link from a buildCart() result.

    Approve-then-handoff only: this is a GET-built link the user must
    manually tap, never a checkout submission performed by this system.
    """
    if not cart.items:
        return WALMART_ADD_TO_CART_URL
    items_param = ",".join(f"{line.item_id}_{line.quantity}" for line in cart.items)
    return f"{WALMART_ADD_TO_CART_URL}?items={items_param}"
