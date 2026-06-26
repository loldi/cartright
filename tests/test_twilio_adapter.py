"""Slice 8: the real Twilio SMS adapter.

The Twilio client is injected as a fake, so no test sends a real message or
needs real Twilio credentials, per the PRD's Testing Decisions.
"""

from __future__ import annotations

from cartright.shopping_engine.adapters.twilio_sms import TwilioSmsAdapter


class _FakeMessages:
    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []

    def create(self, *, to: str, from_: str, body: str) -> None:
        self.created.append({"to": to, "from_": from_, "body": body})


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_send_sms_calls_twilio_with_the_configured_from_number() -> None:
    client = _FakeClient()
    adapter = TwilioSmsAdapter(client, from_number="+15550001111")

    adapter.send_sms(to="+15555550123", body="Deal on coffee: https://x.test/review")

    assert client.messages.created == [
        {
            "to": "+15555550123",
            "from_": "+15550001111",
            "body": "Deal on coffee: https://x.test/review",
        }
    ]


def test_receive_sms_returns_nothing_inbound_is_webhook_driven() -> None:
    adapter = TwilioSmsAdapter(_FakeClient(), from_number="+15550001111")

    assert adapter.receive_sms() == []


def test_satisfies_the_adapter_interface_used_by_the_engine_glue() -> None:
    from cartright.interaction.conversation import handle_inbound_preference
    from cartright.llm.preferences import ParsedPreference
    from cartright.shopping_engine import ShoppingEngine
    from cartright.shopping_engine.adapters.fixtures import (
        FixtureCatalogPricingAdapter,
        FixtureOrderHistoryAdapter,
    )

    class _Parser:
        def parse(self, text: str) -> ParsedPreference:
            return ParsedPreference(item_id="coffee", attributes={}, confirmation="Got it.")

    client = _FakeClient()
    twilio = TwilioSmsAdapter(client, from_number="+15550001111")
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(),
    )

    # The real adapter slots into the exact same glue the fixture is tested with.
    confirmation = handle_inbound_preference(
        "I like Peet's", to="+15555550123", parser=_Parser(), engine=engine, twilio=twilio
    )

    assert confirmation == "Got it."
    assert client.messages.created[0]["body"] == "Got it."
