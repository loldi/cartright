"""Dump reorder candidates for a fixture order history.

A verification aid for the cadence-inference core (Slice 2). Uses only
synthetic fixture data - it never touches a real Walmart account or any
personal order history. Run with: `uv run python scripts/dump_candidates.py`
"""

from __future__ import annotations

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)

# Synthetic, but shaped like real Walmart order lines: a stable item ID (the
# 1:1 catalog key), a messy display title that may drift between orders, and an
# order date. Cadence keys on item_id; the title is only for display.
FIXTURE_ORDERS = [
    {
        "item_id": "10295020",
        "title": "Great Value Paper Towels, 6 Double Rolls",
        "ordered_at": "2026-01-01",
    },
    {
        "item_id": "10295020",
        "title": "Great Value Paper Towels 6 Double Rolls",
        "ordered_at": "2026-01-31",
    },
    {
        "item_id": "10295020",
        "title": "Great Value Paper Towels, 6 Double Rolls",
        "ordered_at": "2026-03-02",
    },
    {
        "item_id": "37774610",
        "title": "Folgers Classic Roast Ground Coffee, 25.9 oz",
        "ordered_at": "2026-01-05",
    },
    {
        "item_id": "37774610",
        "title": "Folgers Classic Roast Ground Coffee 25.9oz",
        "ordered_at": "2026-01-19",
    },
    {
        "item_id": "37774610",
        "title": "Folgers Classic Roast Ground Coffee, 25.9 oz",
        "ordered_at": "2026-02-02",
    },
    {
        "item_id": "10450118",
        "title": "Dawn Ultra Dish Soap, 19.4 fl oz",
        "ordered_at": "2026-01-01",
    },
    {
        "item_id": "10450118",
        "title": "Dawn Ultra Dish Soap, 19.4 fl oz",
        "ordered_at": "2026-01-21",
    },
    {
        "item_id": "10450118",
        "title": "Dawn Ultra Dishwashing Liquid, 19.4 fl oz",
        "ordered_at": "2026-03-02",
    },
    # Single order: no cadence can be inferred, so this should NOT appear.
    {"item_id": "55001234", "title": "GE LED Light Bulbs, 60W, 4-pack", "ordered_at": "2026-02-10"},
]


def main() -> None:
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(FIXTURE_ORDERS),
        catalog=FixtureCatalogPricingAdapter(),
    )

    candidates = engine.getReorderCandidates()
    print(f"{len(candidates)} reorder candidate(s):\n")
    for c in candidates:
        print(f"  [{c.item_id}] {c.title}")
        print(f"      reorder window: {c.window_start} .. {c.window_end}")


if __name__ == "__main__":
    main()
