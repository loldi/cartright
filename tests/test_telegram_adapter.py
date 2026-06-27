"""The real Telegram messaging adapter.

The `httpx.Client` is injected with a `MockTransport`, so no test calls the live
Bot API or needs a real token, per the PRD's Testing Decisions.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from cartright.shopping_engine.adapters.telegram import TelegramMessenger

_TOKEN = "123:TESTTOKEN"


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> TelegramMessenger:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramMessenger(_TOKEN, client=client, api_base="https://api.telegram.test")


def test_send_message_posts_to_send_message_with_chat_id_and_text() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    _adapter(handler).send_message(to="987654321", body="Deal on coffee: https://x.test/review")

    assert seen["url"] == f"https://api.telegram.test/bot{_TOKEN}/sendMessage"
    assert seen["json"] == {
        "chat_id": "987654321",
        "text": "Deal on coffee: https://x.test/review",
    }


def test_non_ok_response_raises_and_never_leaks_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked"})

    with pytest.raises(RuntimeError) as exc_info:
        _adapter(handler).send_message(to="1", body="hi")

    message = str(exc_info.value)
    assert "Forbidden: bot was blocked" in message  # Telegram's own reason is surfaced
    assert "TESTTOKEN" not in message  # the token lives in the URL; never surface it


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

    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    messenger = _adapter(handler)
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=FixtureCatalogPricingAdapter(),
    )

    # The real adapter slots into the exact same glue the fixture is tested with.
    confirmation = handle_inbound_preference(
        "I like Peet's", to="987654321", parser=_Parser(), engine=engine, messenger=messenger
    )

    assert confirmation == "Got it."
    assert sent[0]["text"] == "Got it."
