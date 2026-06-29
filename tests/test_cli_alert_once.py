"""GL-7: the `cartright alert-once` command.

Runs one alert cycle against injected fakes and reports what it sent vs skipped.
No live Claude/Telegram call - a fake composer returns canned text.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from cartright.cli import alert_once
from cartright.llm.alerts import DealAlert
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import CatalogPricingAdapter
from cartright.shopping_engine.adapters.fixtures import (
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)

PAPER_TOWELS = "10295020"
COFFEE = "37774610"
TODAY = date(2026, 6, 21)

# Paper towels window contains TODAY; coffee's window is well before it.
ORDERS = [
    {"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-01", "price": 10.97},
    {"item_id": PAPER_TOWELS, "title": "Paper Towels", "ordered_at": "2026-06-11", "price": 10.97},
    {"item_id": COFFEE, "title": "Coffee", "ordered_at": "2026-05-01", "price": 7.00},
    {"item_id": COFFEE, "title": "Coffee", "ordered_at": "2026-05-08", "price": 7.00},
]


class _Catalog(CatalogPricingAdapter):
    def __init__(self, prices: dict[str, dict[str, Any]]) -> None:
        self._prices = prices

    def get_price(self, item_id: str) -> dict[str, Any]:
        return self._prices.get(item_id, {})


class _FakeComposer:
    def compose(self, deals: list[DealAlert]) -> str:
        return f"Deal on {', '.join(d.title for d in deals)}"


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
    messenger = FixtureMessenger()
    out = io.StringIO()

    code = alert_once(
        engine,
        _FakeComposer(),
        messenger,
        user_chat_id="987654321",
        today=TODAY,
        out=out,
    )

    text = out.getvalue()
    assert code == 0
    assert "1 sent" in text
    assert "1 skipped" in text
    assert f"[{PAPER_TOWELS}]" in text  # the in-window deal got sent
    assert "outside reorder window" in text  # coffee skipped
    assert len(messenger.sent) == 1


def test_alert_once_sends_nothing_when_no_deal() -> None:
    engine = _engine({PAPER_TOWELS: {"price": 10.97, "in_stock": True}})  # full price, no deal
    messenger = FixtureMessenger()
    out = io.StringIO()

    code = alert_once(
        engine,
        _FakeComposer(),
        messenger,
        user_chat_id="987654321",
        today=TODAY,
        out=out,
    )

    assert code == 0
    assert "0 sent" in out.getvalue()
    assert messenger.sent == []


# ---- operator-seat: partial failure paths -----------------------------------


class _BoomComposer:
    def compose(self, deals: list[DealAlert]) -> str:
        raise RuntimeError("Claude API unavailable")


class _BoomMessenger(FixtureMessenger):
    def send_message(
        self,
        to: str,
        body: str,
        *,
        parse_mode: str | None = None,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> None:
        raise RuntimeError("Telegram send failed")


def test_alert_once_composer_error_reports_per_item_not_traceback() -> None:
    """If compose() raises, the cycle reports each in-window item as failed, not a crash."""
    engine = _engine({PAPER_TOWELS: {"price": 8.97, "was_price": 10.97, "in_stock": True}})
    out = io.StringIO()

    code = alert_once(
        engine,
        _BoomComposer(),
        FixtureMessenger(),
        user_chat_id="987654321",
        today=TODAY,
        out=out,
    )

    text = out.getvalue()
    assert code == 0  # alert-once itself is not an error; the cycle ran
    assert "0 sent" in text
    assert any(phrase in text.lower() for phrase in ("runtimeerror", "send failed", "failed"))
    assert f"[{PAPER_TOWELS}]" in text  # item is listed (as failed/skipped)


def test_alert_once_messenger_error_reports_per_item_not_traceback() -> None:
    """If send_message() raises, the cycle reports each in-window item as failed, not a crash."""
    engine = _engine({PAPER_TOWELS: {"price": 8.97, "was_price": 10.97, "in_stock": True}})
    out = io.StringIO()

    code = alert_once(
        engine,
        _FakeComposer(),
        _BoomMessenger(),
        user_chat_id="987654321",
        today=TODAY,
        out=out,
    )

    text = out.getvalue()
    assert code == 0
    assert "0 sent" in text
    assert f"[{PAPER_TOWELS}]" in text
