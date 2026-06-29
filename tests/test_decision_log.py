"""Audit trail: why did the engine alert (or skip) a given reorder candidate.

`recordDecision`/`getDecisionLog` persist one row per candidate per cycle so a
real production run can be inspected after the fact, not just the instant it
happened (see RETROSPECTIVE.md, 2026-06-29).

`lastAlertedPrice` backs the once-per-window dedup fix (RETROSPECTIVE.md,
2026-06-29 "Duplicate alert on every scheduler tick"): without it, a still-active
deal gets re-sent on every hourly cycle (or restart) for as long as it stays in
its reorder window, which is exactly the spammy behavior the product is not
supposed to be. It returns a price (not just a bool) so a *further* price drop
within the same window still gets a follow-up alert - see
"Re-alert on a further price drop within the same window" below.
"""

from __future__ import annotations

import pytest

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)


@pytest.fixture
def engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(),
    )


def test_recorded_decision_is_read_back(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="10295020",
        title="Paper Towels",
        sent=True,
        reason="deal: $2.00 off",
        body="Paper towels are on sale!",
        window_start="2026-06-01",
        window_end="2026-06-03",
    )

    entries = engine.getDecisionLog()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.item_id == "10295020"
    assert entry.title == "Paper Towels"
    assert entry.sent is True
    assert entry.reason == "deal: $2.00 off"
    assert entry.body == "Paper towels are on sale!"
    assert entry.window_start == "2026-06-01"
    assert entry.window_end == "2026-06-03"
    assert entry.recorded_at  # a real timestamp was stamped, not blank


def test_skipped_decision_has_no_body(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="37774610",
        title="Coffee",
        sent=False,
        reason="outside reorder window (2026-05-14..2026-05-16)",
        body=None,
        window_start="2026-05-14",
        window_end="2026-05-16",
    )

    entries = engine.getDecisionLog()

    assert entries[0].sent is False
    assert entries[0].body is None


def test_decision_log_returns_most_recent_first(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="a",
        title="A",
        sent=False,
        reason="first",
        body=None,
        window_start="2026-01-01",
        window_end="2026-01-03",
    )
    engine.recordDecision(
        item_id="b",
        title="B",
        sent=False,
        reason="second",
        body=None,
        window_start="2026-01-01",
        window_end="2026-01-03",
    )

    entries = engine.getDecisionLog()

    assert [e.item_id for e in entries] == ["b", "a"]


def test_decision_log_respects_limit(engine: ShoppingEngine) -> None:
    for i in range(5):
        engine.recordDecision(
            item_id=str(i),
            title=str(i),
            sent=False,
            reason="r",
            body=None,
            window_start="2026-01-01",
            window_end="2026-01-03",
        )

    entries = engine.getDecisionLog(limit=2)

    assert [e.item_id for e in entries] == ["4", "3"]


def test_last_alerted_price_is_none_when_nothing_recorded(engine: ShoppingEngine) -> None:
    assert engine.lastAlertedPrice("a", "2026-01-01", "2026-01-03") is None


def test_last_alerted_price_after_a_sent_decision(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="a",
        title="A",
        sent=True,
        reason="deal: $1 off",
        body="alert",
        window_start="2026-01-01",
        window_end="2026-01-03",
        price=10.97,
    )

    assert engine.lastAlertedPrice("a", "2026-01-01", "2026-01-03") == 10.97


def test_skipped_decisions_do_not_count_as_alerted(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="a",
        title="A",
        sent=False,
        reason="in window, but no real deal",
        body=None,
        window_start="2026-01-01",
        window_end="2026-01-03",
    )

    assert engine.lastAlertedPrice("a", "2026-01-01", "2026-01-03") is None


def test_last_alerted_price_is_specific_to_the_window(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="a",
        title="A",
        sent=True,
        reason="deal: $1 off",
        body="alert",
        window_start="2026-01-01",
        window_end="2026-01-03",
        price=10.97,
    )

    # A later cycle's window (e.g. after a new order pushes cadence forward) is
    # a new reorder occasion - the old alert shouldn't suppress a new one.
    assert engine.lastAlertedPrice("a", "2026-02-01", "2026-02-03") is None


def test_last_alerted_price_reflects_the_most_recent_sent_decision(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="a",
        title="A",
        sent=True,
        reason="first alert",
        body="x",
        window_start="2026-01-01",
        window_end="2026-01-03",
        price=10.97,
    )
    engine.recordDecision(
        item_id="a",
        title="A",
        sent=True,
        reason="price dropped further",
        body="y",
        window_start="2026-01-01",
        window_end="2026-01-03",
        price=9.50,
    )

    assert engine.lastAlertedPrice("a", "2026-01-01", "2026-01-03") == 9.50
