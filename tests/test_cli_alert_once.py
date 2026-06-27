"""GL-7: the `cartright alert-once` command.

Runs one alert cycle against injected fakes and reports what it sent vs skipped.
No live Claude/Twilio call - a fake composer returns canned text.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from cartright.cli import alert_once
from cartright.scheduler import build_review_url
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import CatalogPricingAdapter
from cartright.shopping_engine.adapters.fixtures import (
    FixtureOrderHistoryAdapter,
    FixtureTwilioAdapter,
)
from cartright.shopping_engine.engine import ReorderCandidate
from cartright.shopping_engine.pricing import DealEvaluation

PAPER_TOWELS = "10295020"
COFFEE = "37774610"
TODAY = date(2026, 6, 21)

# Paper towels window contains TODAY; coffee's window is well before it.
ORDERS = [
    {"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-01"},
    {"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-11"},
    {"item_id": COFFEE, "title": "Coffee", "ordered_at": "2026-05-01"},
    {"item_id": COFFEE, "title": "Coffee", "ordered_at": "2026-05-08"},
]


class _Catalog(CatalogPricingAdapter):
    def __init__(self, prices: dict[str, dict[str, Any]]) -> None:
        self._prices = prices

    def get_price(self, item_id: str) -> dict[str, Any]:
        return self._prices.get(item_id, {})


class _FakeComposer:
    def compose(self, candidate: ReorderCandidate, deal: DealEvaluation, review_url: str) -> str:
        return f"Deal on {candidate.title}: {review_url}"


def _engine(prices: dict[str, dict[str, Any]]) -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(ORDERS), catalog=_Catalog(prices)
    )


def test_alert_once_reports_sent_and_skipped() -> None:
    engine = _engine(
        {
            PAPER_TOWELS: {"price": 8.97, "was_price": 10.97, "in_stock": True},
            COFFEE: {"price": 5.00, "was_price": 7.00, "in_stock": True},
        }
    )
    twilio = FixtureTwilioAdapter()
    out = io.StringIO()

    code = alert_once(
        engine,
        _FakeComposer(),
        twilio,
        user_number="+15555550123",
        review_base_url="https://x.test/review",
        today=TODAY,
        out=out,
    )

    text = out.getvalue()
    assert code == 0
    assert "1 sent" in text
    assert "1 skipped" in text
    assert f"[{PAPER_TOWELS}]" in text  # the in-window deal got sent
    assert "outside reorder window" in text  # coffee skipped
    assert len(twilio.sent) == 1


def test_alert_once_sends_nothing_when_no_deal() -> None:
    engine = _engine({PAPER_TOWELS: {"price": 10.97, "in_stock": True}})  # full price, no deal
    twilio = FixtureTwilioAdapter()
    out = io.StringIO()

    code = alert_once(
        engine,
        _FakeComposer(),
        twilio,
        user_number="+15555550123",
        review_base_url="https://x.test/review",
        today=TODAY,
        out=out,
    )

    assert code == 0
    assert "0 sent" in out.getvalue()
    assert twilio.sent == []


def test_build_review_url_is_token_ready() -> None:
    assert build_review_url("https://x.test/review", "abc") == "https://x.test/review?item=abc"
    # The token seam exists for hardening #27, unused by default today.
    assert (
        build_review_url("https://x.test/review", "abc", token="sig")
        == "https://x.test/review?item=abc&token=sig"
    )
