"""Audit trail: why did the engine alert (or skip) a given reorder candidate.

`recordDecision`/`getDecisionLog` persist one row per candidate per cycle so a
real production run can be inspected after the fact, not just the instant it
happened (see RETROSPECTIVE.md, 2026-06-29).
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
    )

    entries = engine.getDecisionLog()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.item_id == "10295020"
    assert entry.title == "Paper Towels"
    assert entry.sent is True
    assert entry.reason == "deal: $2.00 off"
    assert entry.body == "Paper towels are on sale!"
    assert entry.recorded_at  # a real timestamp was stamped, not blank


def test_skipped_decision_has_no_body(engine: ShoppingEngine) -> None:
    engine.recordDecision(
        item_id="37774610",
        title="Coffee",
        sent=False,
        reason="outside reorder window (2026-05-14..2026-05-16)",
        body=None,
    )

    entries = engine.getDecisionLog()

    assert entries[0].sent is False
    assert entries[0].body is None


def test_decision_log_returns_most_recent_first(engine: ShoppingEngine) -> None:
    engine.recordDecision(item_id="a", title="A", sent=False, reason="first", body=None)
    engine.recordDecision(item_id="b", title="B", sent=False, reason="second", body=None)

    entries = engine.getDecisionLog()

    assert [e.item_id for e in entries] == ["b", "a"]


def test_decision_log_respects_limit(engine: ShoppingEngine) -> None:
    for i in range(5):
        engine.recordDecision(item_id=str(i), title=str(i), sent=False, reason="r", body=None)

    entries = engine.getDecisionLog(limit=2)

    assert [e.item_id for e in entries] == ["4", "3"]
