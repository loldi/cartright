"""Hardening: /telegram rate limit.

The webhook secret + chat_id allowlist already keep strangers out (see
test_telegram_webhook_secret.py). This covers the remaining gap: if the
webhook secret ever leaked, the *real* user's chat_id could still be used to
flood the endpoint and run up live Claude API spend. A spy parser proves a
rejected request makes zero Claude calls.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.ratelimit import RateLimiter
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)

USER_CHAT_ID = "987654321"


class _SpyParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, text: str) -> ParsedPreference:
        self.calls += 1
        return ParsedPreference(item_id="coffee", attributes={}, confirmation="Got it.")


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


def _client(parser: _SpyParser, rate_limiter: RateLimiter) -> TestClient:
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(), catalog=FixtureCatalogPricingAdapter()
    )
    app = create_app(
        parser=parser,
        engine=engine,
        messenger=FixtureMessenger(),
        user_chat_id=USER_CHAT_ID,
        validate_webhook=False,
        rate_limiter=rate_limiter,
    )
    return TestClient(app)


def test_rate_limit_returns_429_and_makes_no_claude_call() -> None:
    parser = _SpyParser()
    client = _client(parser, RateLimiter(max_requests=1, window_seconds=60.0))

    first = client.post("/telegram", json=_update(int(USER_CHAT_ID), "I only drink Peet's"))
    second = client.post("/telegram", json=_update(int(USER_CHAT_ID), "actually never mind"))

    assert first.status_code == 200
    assert second.status_code == 429
    assert parser.calls == 1  # only the first update reached the parser


def test_under_the_limit_is_unaffected() -> None:
    parser = _SpyParser()
    client = _client(parser, RateLimiter(max_requests=5, window_seconds=60.0))

    for _ in range(5):
        response = client.post("/telegram", json=_update(int(USER_CHAT_ID), "hi"))
        assert response.status_code == 200

    assert parser.calls == 5
