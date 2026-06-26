from fastapi.testclient import TestClient

from cartright.interaction.conversation import handle_inbound_preference
from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
    FixtureTwilioAdapter,
)

USER = "+15555550123"


class FakeParser:
    """Stand-in for the LLM: returns a preset ParsedPreference, records the text."""

    def __init__(self, result: ParsedPreference) -> None:
        self._result = result
        self.seen: list[str] = []

    def parse(self, text: str) -> ParsedPreference:
        self.seen.append(text)
        return self._result


def make_engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(),
    )


def test_inbound_preference_is_recorded_and_confirmed() -> None:
    engine = make_engine()
    twilio = FixtureTwilioAdapter()
    parser = FakeParser(
        ParsedPreference(
            item_id="paper-towels",
            attributes={"brand": "Bounty", "substitution_ok": False},
            confirmation="Got it - always Bounty paper towels, no substitutes.",
        )
    )

    confirmation = handle_inbound_preference(
        "always get the Bounty, never the store brand",
        to=USER,
        parser=parser,
        engine=engine,
        twilio=twilio,
    )

    pref = engine.getPreference("paper-towels")
    assert pref is not None
    assert pref.source == "explicit"
    assert pref.attributes == {"brand": "Bounty", "substitution_ok": False}
    assert twilio.sent == [{"to": USER, "body": confirmation}]


def test_sms_webhook_captures_preference_end_to_end() -> None:
    engine = make_engine()
    twilio = FixtureTwilioAdapter()
    parser = FakeParser(
        ParsedPreference(
            item_id="coffee",
            attributes={"brand": "Peet's"},
            confirmation="Noted - Peet's coffee from now on.",
        )
    )
    client = TestClient(create_app(parser=parser, engine=engine, twilio=twilio, user_number=USER))

    response = client.post("/sms", data={"From": USER, "Body": "I only drink Peet's"})

    assert response.status_code == 200
    assert parser.seen == ["I only drink Peet's"]
    assert engine.getPreference("coffee") is not None
    assert twilio.sent == [{"to": USER, "body": "Noted - Peet's coffee from now on."}]


def test_sms_webhook_ignores_messages_from_other_numbers() -> None:
    engine = make_engine()
    twilio = FixtureTwilioAdapter()
    parser = FakeParser(ParsedPreference(item_id="coffee", attributes={}, confirmation="ok"))
    client = TestClient(create_app(parser=parser, engine=engine, twilio=twilio, user_number=USER))

    response = client.post("/sms", data={"From": "+19998887777", "Body": "I only drink Peet's"})

    assert response.status_code == 200
    assert parser.seen == []
    assert twilio.sent == []
    assert engine.getPreference("coffee") is None
