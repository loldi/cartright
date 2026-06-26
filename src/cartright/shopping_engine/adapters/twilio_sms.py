from __future__ import annotations

import os
from typing import Any, Protocol

from cartright.shopping_engine.adapters.base import TwilioAdapter


class _TwilioClient(Protocol):
    """The slice of the twilio SDK this adapter actually uses.

    Declaring it as a Protocol keeps the adapter testable with a tiny fake and
    avoids leaking the full `twilio.rest.Client` surface into our types.
    """

    @property
    def messages(self) -> Any: ...


class TwilioSmsAdapter(TwilioAdapter):
    """Real outbound SMS via the Twilio REST API.

    Satisfies `TwilioAdapter`, so it drops into production wiring in place of
    `FixtureTwilioAdapter`. The Twilio `Client` is injectable so tests can pass
    a fake and never send a real message; `from_env()` builds the real client.

    Inbound SMS is *not* polled here: Twilio pushes inbound messages to the
    `/sms` webhook (see `interaction/web.py`), so `receive_sms` returns nothing.
    """

    def __init__(self, client: _TwilioClient, from_number: str) -> None:
        self._client = client
        self._from_number = from_number

    @classmethod
    def from_env(cls) -> TwilioSmsAdapter:
        """Production constructor: real Twilio client from environment secrets."""
        from twilio.rest import Client  # type: ignore[import-untyped]

        client = Client(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        )
        return cls(client, os.environ["TWILIO_FROM_NUMBER"])

    def send_sms(self, to: str, body: str) -> None:
        self._client.messages.create(to=to, from_=self._from_number, body=body)

    def receive_sms(self) -> list[dict[str, Any]]:
        # Inbound is delivered by Twilio to the /sms webhook, not polled.
        return []
