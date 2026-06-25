from __future__ import annotations

import json
from typing import Any

import anthropic

from cartright.llm.preferences import ParsedPreference
from cartright.shopping_engine.engine import ReorderCandidate
from cartright.shopping_engine.pricing import DealEvaluation

# The PRD pins the LLM to Claude Sonnet via the Claude API.
_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are Cartright, a personal shopping assistant the user texts like a friend.
The user just told you a shopping preference in casual language. Extract it into
a structured preference for a single item or category.

- item_id: a short, stable, lowercase-kebab identifier for the item or category
  the preference is about (e.g. "paper-towels", "coffee", "dish-soap").
- attributes: the concrete preferences stated, as key/value pairs. Common keys
  are "brand", "size", "never_substitute". Only include what the user actually
  said; do not invent attributes.
- confirmation: one short, friendly SMS (no more than ~160 chars) confirming
  back what you recorded, in your own voice.
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "attributes": {"type": "object", "additionalProperties": True},
        "confirmation": {"type": "string"},
    },
    "required": ["item_id", "attributes", "confirmation"],
    "additionalProperties": False,
}


class ClaudePreferenceParser:
    """Parses a preference statement with a live Claude completion.

    Satisfies the `PreferenceParser` protocol. Constructed with an Anthropic
    client so callers (and tests, if they ever want to) can inject their own.
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def parse(self, text: str) -> ParsedPreference:
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": text}],
        )
        payload = next(block.text for block in response.content if block.type == "text")
        data: dict[str, Any] = json.loads(payload)
        return ParsedPreference(
            item_id=data["item_id"],
            attributes=data["attributes"],
            confirmation=data["confirmation"],
        )


_ALERT_SYSTEM = """\
You are Cartright, a personal shopping assistant who texts the user proactively
only when something genuinely worth their time has come up. You are given a
real, already-confirmed deal on something the user is due to reorder. Compose
one short, friendly SMS announcing it.

- Use ONLY the item, price, and savings figures given to you below - never
  invent or round a price, a discount, or a timing claim of your own.
- Include the review link given to you verbatim so the user can open the real
  itemized cart.
- Keep it under ~300 characters, like a text from a person, not an ad.
"""


class ClaudeAlertComposer:
    """Composes a proactive deal-alert SMS with a live Claude completion.

    Satisfies the `AlertComposer` protocol. Every fact in the prompt (price,
    savings, title, review link) is already-real `ShoppingEngine` output -
    the LLM only ever rephrases those facts into a friendly SMS, it never
    decides what the deal is or invents a number itself.
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def compose(self, candidate: ReorderCandidate, deal: DealEvaluation, review_url: str) -> str:
        assert deal.current_price is not None and deal.reference_price is not None
        prompt = (
            f"Item: {candidate.title}\n"
            f"Current price: ${deal.current_price:.2f}\n"
            f"Was: ${deal.reference_price:.2f}\n"
            f"Savings: ${deal.savings:.2f}\n"
            f"Review link: {review_url}"
        )
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=256,
            system=_ALERT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return next(block.text for block in response.content if block.type == "text")
