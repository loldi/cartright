from fastapi.testclient import TestClient

from cartright.interaction.conversation import handle_inbound_preference
from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)

USER_CHAT_ID = "987654321"


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


def _update(chat_id: str, text: str) -> dict[str, object]:
    return {
        "update_id": 1,
        "message": {
            "from": {"id": int(chat_id)},
            "chat": {"id": int(chat_id), "type": "private"},
            "text": text,
        },
    }


def test_inbound_preference_is_recorded_and_confirmed() -> None:
    engine = make_engine()
    messenger = FixtureMessenger()
    parser = FakeParser(
        ParsedPreference(
            item_id="paper-towels",
            attributes={"brand": "Bounty", "substitution_ok": False},
            confirmation="Got it - always Bounty paper towels, no substitutes.",
        )
    )

    confirmation = handle_inbound_preference(
        "always get the Bounty, never the store brand",
        to=USER_CHAT_ID,
        parser=parser,
        engine=engine,
        messenger=messenger,
    )

    pref = engine.getPreference("paper-towels")
    assert pref is not None
    assert pref.source == "explicit"
    assert pref.attributes == {"brand": "Bounty", "substitution_ok": False}
    assert messenger.sent == [{"to": USER_CHAT_ID, "body": confirmation}]


def test_telegram_webhook_captures_preference_end_to_end() -> None:
    engine = make_engine()
    messenger = FixtureMessenger()
    parser = FakeParser(
        ParsedPreference(
            item_id="coffee",
            attributes={"brand": "Peet's"},
            confirmation="Noted - Peet's coffee from now on.",
        )
    )
    client = TestClient(
        create_app(
            parser=parser,
            engine=engine,
            messenger=messenger,
            user_chat_id=USER_CHAT_ID,
            validate_webhook=False,
        )
    )

    response = client.post("/telegram", json=_update(USER_CHAT_ID, "I only drink Peet's"))

    assert response.status_code == 200
    assert parser.seen == ["I only drink Peet's"]
    assert engine.getPreference("coffee") is not None
    assert messenger.sent == [{"to": USER_CHAT_ID, "body": "Noted - Peet's coffee from now on."}]


def test_telegram_webhook_ignores_messages_from_other_chats() -> None:
    engine = make_engine()
    messenger = FixtureMessenger()
    parser = FakeParser(ParsedPreference(item_id="coffee", attributes={}, confirmation="ok"))
    client = TestClient(
        create_app(
            parser=parser,
            engine=engine,
            messenger=messenger,
            user_chat_id=USER_CHAT_ID,
            validate_webhook=False,
        )
    )

    response = client.post("/telegram", json=_update("11112222", "I only drink Peet's"))

    assert response.status_code == 200
    assert parser.seen == []
    assert messenger.sent == []
    assert engine.getPreference("coffee") is None
