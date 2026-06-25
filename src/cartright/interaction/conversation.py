from __future__ import annotations

from cartright.llm.preferences import PreferenceParser
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import TwilioAdapter


def handle_inbound_preference(
    text: str,
    to: str,
    *,
    parser: PreferenceParser,
    engine: ShoppingEngine,
    twilio: TwilioAdapter,
) -> str:
    """Capture an explicit preference stated over SMS, end to end.

    The LLM interprets the casual text, the engine persists it as an explicit
    preference, and a confirmation SMS is sent back. Returns the confirmation
    body that was sent.
    """
    parsed = parser.parse(text)
    engine.recordPreference(parsed.item_id, parsed.attributes, source="explicit")
    twilio.send_sms(to=to, body=parsed.confirmation)
    return parsed.confirmation
