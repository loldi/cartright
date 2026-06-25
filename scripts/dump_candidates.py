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

FIXTURE_ORDERS = [
    {"item_id": "paper-towels", "ordered_at": "2026-01-01"},
    {"item_id": "paper-towels", "ordered_at": "2026-01-31"},
    {"item_id": "paper-towels", "ordered_at": "2026-03-02"},
    {"item_id": "coffee", "ordered_at": "2026-01-05"},
    {"item_id": "coffee", "ordered_at": "2026-01-19"},
    {"item_id": "coffee", "ordered_at": "2026-02-02"},
    {"item_id": "dish-soap", "ordered_at": "2026-01-01"},
    {"item_id": "dish-soap", "ordered_at": "2026-01-21"},
    {"item_id": "dish-soap", "ordered_at": "2026-03-02"},
    # Single order: no cadence can be inferred, so this should NOT appear.
    {"item_id": "light-bulbs", "ordered_at": "2026-02-10"},
]


def main() -> None:
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(FIXTURE_ORDERS),
        catalog=FixtureCatalogPricingAdapter(),
    )

    candidates = engine.getReorderCandidates()
    print(f"{len(candidates)} reorder candidate(s):\n")
    for c in candidates:
        print(f"  {c.item_id:<14} reorder window: {c.window_start} .. {c.window_end}")


if __name__ == "__main__":
    main()
