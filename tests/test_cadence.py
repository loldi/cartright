from typing import Any

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)


def make_engine(orders: list[dict[str, Any]]) -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(orders),
        catalog=FixtureCatalogPricingAdapter(),
    )


def order(item_id: str, ordered_at: str) -> dict[str, Any]:
    return {"item_id": item_id, "ordered_at": ordered_at}


def test_regular_cadence_predicts_window_after_last_order() -> None:
    engine = make_engine(
        [
            order("paper-towels", "2026-01-01"),
            order("paper-towels", "2026-01-31"),  # +30 days
            order("paper-towels", "2026-03-02"),  # +30 days
        ]
    )

    candidates = engine.getReorderCandidates()

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.item_id == "paper-towels"
    # avg gap 30d; last order 2026-03-02; predicted 2026-04-01; regular cadence
    # so the margin floors at 1 day.
    assert candidate.window_start == "2026-03-31"
    assert candidate.window_end == "2026-04-02"


def test_single_order_yields_no_candidate() -> None:
    engine = make_engine([order("paper-towels", "2026-01-01")])

    assert engine.getReorderCandidates() == []


def test_empty_history_yields_no_candidates() -> None:
    engine = make_engine([])

    assert engine.getReorderCandidates() == []


def test_distinct_items_get_independent_candidates() -> None:
    engine = make_engine(
        [
            # paper towels: 30-day cadence
            order("paper-towels", "2026-01-01"),
            order("paper-towels", "2026-01-31"),
            # coffee: 14-day cadence, interleaved in the history
            order("coffee", "2026-01-05"),
            order("coffee", "2026-01-19"),
            order("coffee", "2026-02-02"),
        ]
    )

    candidates = engine.getReorderCandidates()
    by_item = {c.item_id: c for c in candidates}

    assert set(by_item) == {"paper-towels", "coffee"}
    # paper-towels: last 2026-01-31 + 30d = 2026-03-02
    assert by_item["paper-towels"].window_start == "2026-03-01"
    assert by_item["paper-towels"].window_end == "2026-03-03"
    # coffee: last 2026-02-02 + 14d = 2026-02-16, independent of paper-towels
    assert by_item["coffee"].window_start == "2026-02-15"
    assert by_item["coffee"].window_end == "2026-02-17"


def test_irregular_intervals_widen_the_window() -> None:
    engine = make_engine(
        [
            order("dish-soap", "2026-01-01"),
            order("dish-soap", "2026-01-21"),  # +20 days
            order("dish-soap", "2026-03-02"),  # +40 days
        ]
    )

    candidates = engine.getReorderCandidates()

    assert len(candidates) == 1
    candidate = candidates[0]
    # gaps [20, 40]: avg 30 -> predicted 2026-03-02 + 30d = 2026-04-01;
    # margin = (40 - 20) / 2 = 10 days, so the window spans +/- 10 days.
    assert candidate.window_start == "2026-03-22"
    assert candidate.window_end == "2026-04-11"


def test_unsorted_order_history_is_handled() -> None:
    # Real scraped order history won't arrive in date order.
    engine = make_engine(
        [
            order("paper-towels", "2026-03-02"),
            order("paper-towels", "2026-01-01"),
            order("paper-towels", "2026-01-31"),
        ]
    )

    candidates = engine.getReorderCandidates()

    assert len(candidates) == 1
    # Same regular-cadence result as the sorted tracer case.
    assert candidates[0].window_start == "2026-03-31"
    assert candidates[0].window_end == "2026-04-02"
