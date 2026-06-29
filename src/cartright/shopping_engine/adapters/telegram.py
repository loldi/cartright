from __future__ import annotations

import os
from typing import Any

import httpx

from cartright.shopping_engine.adapters.base import Messenger

# Public Telegram Bot API. The bot token is part of the URL path, so it must
# never appear in a log line or an exception message (see send_message).
DEFAULT_API_BASE = "https://api.telegram.org"


class TelegramMessenger(Messenger):
    """Outbound messages via the Telegram Bot API `sendMessage` method.

    Satisfies `Messenger`, so it drops into production wiring in place of the
    fixture. The `httpx.Client` is injectable: tests pass one backed by
    `httpx.MockTransport` so no test ever calls the live Bot API.

    Inbound is *not* polled here. Telegram pushes updates to the `/telegram`
    webhook (see `interaction/web.py`), which hands the text to the engine.
    """

    def __init__(
        self,
        token: str,
        *,
        client: httpx.Client | None = None,
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._client = client or httpx.Client(timeout=10.0)

    @classmethod
    def from_env(cls) -> TelegramMessenger:
        """Production constructor: bot token from the environment."""
        return cls(os.environ["TELEGRAM_BOT_TOKEN"])

    def send_message(
        self,
        to: str,
        body: str,
        *,
        parse_mode: str | None = None,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> None:
        """Send `body` to chat id `to`. Raises on a non-OK Bot API response.

        Link previews are always disabled: a real product URL anywhere in the
        message (the linked item name, or a future deep link) would otherwise
        balloon into a large OpenGraph preview card - caught live, see
        PRD.md's "Alert message format" decision.

        The token lives in the request URL, so on failure we surface Telegram's
        own `description` (or a truncated body) and the status code - never the
        URL or the raw exception, either of which would leak the token.
        """
        payload: dict[str, Any] = {
            "chat_id": to,
            "text": body,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if button_text and button_url:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": button_text, "url": button_url}]]
            }
        response = self._client.post(
            f"{self._api_base}/bot{self._token}/sendMessage",
            json=payload,
        )
        if response.status_code != 200:
            detail = ""
            try:
                detail = str(response.json().get("description", ""))
            except Exception:
                detail = response.text[:200]
            raise RuntimeError(
                f"Telegram sendMessage failed (HTTP {response.status_code}): {detail}"
            )
