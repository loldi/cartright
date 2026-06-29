"""The `cartright decisions` command: the audit-trail reader for go-live."""

from __future__ import annotations

import io

from cartright.cli import decisions
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
)


def _engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(), catalog=FixtureCatalogPricingAdapter()
    )


def test_decisions_reports_nothing_recorded_yet() -> None:
    out = io.StringIO()

    code = decisions(_engine(), out=out)

    assert code == 0
    assert "No decisions recorded yet." in out.getvalue()


def test_decisions_prints_recorded_rows_most_recent_first() -> None:
    engine = _engine()
    engine.recordDecision(
        item_id="a",
        title="Paper Towels",
        sent=True,
        reason="deal: $2 off",
        body="x",
        window_start="2026-01-01",
        window_end="2026-01-03",
    )
    engine.recordDecision(
        item_id="b",
        title="Coffee",
        sent=False,
        reason="outside reorder window",
        body=None,
        window_start="2025-05-14",
        window_end="2025-05-16",
    )
    out = io.StringIO()

    code = decisions(engine, out=out)

    lines = out.getvalue().splitlines()
    assert code == 0
    assert "[SENT]" not in lines[0] and "[b] Coffee" in lines[0]
    assert "[a] Paper Towels" in lines[1] and "[SENT]" in lines[1]


def test_decisions_respects_limit() -> None:
    engine = _engine()
    for i in range(3):
        engine.recordDecision(
            item_id=str(i),
            title=str(i),
            sent=False,
            reason="r",
            body=None,
            window_start="2026-01-01",
            window_end="2026-01-03",
        )
    out = io.StringIO()

    decisions(engine, limit=1, out=out)

    assert len(out.getvalue().splitlines()) == 1
