from __future__ import annotations

import os

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

    def send_message(self, to: str, body: str) -> None:
        """Send `body` to chat id `to`. Raises on a non-OK Bot API response.

        The token lives in the request URL, so on failure we surface Telegram's
        own `description` (or a truncated body) and the status code - never the
        URL or the raw exception, either of which would leak the token.
        """
        response = self._client.post(
            f"{self._api_base}/bot{self._token}/sendMessage",
            json={"chat_id": to, "text": body},
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
