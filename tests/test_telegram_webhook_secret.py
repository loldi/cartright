"""The /telegram webhook validates the secret-token header (fail-closed).

No real Telegram call: updates are plain JSON, and the secret token is the
shared value Telegram echoes in the X-Telegram-Bot-Api-Secret-Token header.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)

USER_CHAT_ID = "987654321"
SECRET = "test-webhook-secret-abc123"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class _Parser:
    def parse(self, text: str) -> ParsedPreference:
        return ParsedPreference(item_id="coffee", attributes={}, confirmation="Got it.")


def _engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(), catalog=FixtureCatalogPricingAdapter()
    )


def _client(
    engine: ShoppingEngine, messenger: FixtureMessenger, *, validate: bool = True
) -> TestClient:
    app = create_app(
        parser=_Parser(),
        engine=engine,
        messenger=messenger,
        user_chat_id=USER_CHAT_ID,
        webhook_secret=SECRET,
        validate_webhook=validate,
    )
    return TestClient(app)


def _update(chat_id: int, text: str) -> dict[str, object]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": chat_id},
            "chat": {"id": chat_id, "type": "private"},
            "date": 0,
            "text": text,
        },
    }


def test_valid_secret_is_accepted_and_records_the_preference() -> None:
    engine, messenger = _engine(), FixtureMessenger()
    client = _client(engine, messenger)

    response = client.post(
        "/telegram",
        json=_update(int(USER_CHAT_ID), "I only drink Peet's"),
        headers={SECRET_HEADER: SECRET},
    )

    assert response.status_code == 200
    assert engine.getPreference("coffee") is not None
    assert messenger.sent == [{"to": USER_CHAT_ID, "body": "Got it."}]


def test_missing_secret_is_rejected_fail_closed() -> None:
    engine, messenger = _engine(), FixtureMessenger()
    client = _client(engine, messenger)

    response = client.post("/telegram", json=_update(int(USER_CHAT_ID), "hi"))

    assert response.status_code == 403
    assert engine.getPreference("coffee") is None
    assert messenger.sent == []


def test_wrong_secret_is_rejected() -> None:
    engine, messenger = _engine(), FixtureMessenger()
    client = _client(engine, messenger)

    response = client.post(
        "/telegram",
        json=_update(int(USER_CHAT_ID), "hi"),
        headers={SECRET_HEADER: "not-the-secret"},
    )

    assert response.status_code == 403
    assert engine.getPreference("coffee") is None


def test_valid_secret_from_wrong_chat_is_still_ignored() -> None:
    engine, messenger = _engine(), FixtureMessenger()
    client = _client(engine, messenger)

    response = client.post(
        "/telegram",
        json=_update(11112222, "I only drink Peet's"),
        headers={SECRET_HEADER: SECRET},
    )

    # Secret is valid (not a 403), but the chat isn't the served one, so nothing
    # is recorded.
    assert response.status_code == 200
    assert engine.getPreference("coffee") is None
    assert messenger.sent == []


def test_validation_can_be_disabled_for_local_use() -> None:
    engine, messenger = _engine(), FixtureMessenger()
    client = _client(engine, messenger, validate=False)

    response = client.post("/telegram", json=_update(int(USER_CHAT_ID), "hi"))

    assert response.status_code == 200
    assert engine.getPreference("coffee") is not None
