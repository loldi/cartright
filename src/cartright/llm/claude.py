from __future__ import annotations

import json
from typing import Any

import anthropic

from cartright.llm.alerts import DealAlert
from cartright.llm.preferences import ParsedPreference

# The PRD pins the LLM to Claude Sonnet via the Claude API.
_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are Cartright, a personal shopping assistant the user texts like a friend.
The user just told you a shopping preference in casual language. Extract it into
a structured preference for a single item or category.

- item_id: a short, stable, lowercase-kebab identifier for the item or category
  the preference is about (e.g. "paper-towels", "coffee", "dish-soap").
- attributes: the concrete preferences stated, as key/value pairs. Common keys
  are "brand", "size", and "substitution_ok". Only include what the user
  actually said; do not invent attributes. Substitution is default-deny: set
  "substitution_ok": true ONLY when the user explicitly allows a substitute for
  this item (e.g. "any brand is fine", "sub it if they're out"). A user who says
  "never substitute" needs no attribute at all - deny is already the default, so
  just omit it.
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
only when something genuinely worth their time has come up. You are given one
or more real, already-confirmed deals on items the user is due to reorder.
Compose a single Telegram message using only Telegram's HTML formatting
(<b> and <a href="..."> tags - nothing else, no markdown, no code fences).

Structure, exactly:
1. Open with a short, casual one-line greeting (e.g. "Hey there,").
2. One deal: a single line - the item name as a bold hyperlink
   (<b><a href="PRODUCT_URL">Name</a></b>), then the price bold, then a plain
   parenthetical: "(you paid $X last time, save $Y)" if a last-paid price is
   given, otherwise "(was $X, save $Y)" using the reference price instead.
   More than one deal: a short intro line, then each item on its own bullet
   line ("• ") in that same shape.
3. End with one short, plain paragraph (no bold/italic/links) giving the
   reorder-cadence context you're given (the window dates) - nothing else.

Rules:
- Use ONLY the facts given to you below for each deal - never invent or round
  a price, a discount, or a timing claim of your own.
- If an item has no product_url, don't hyperlink its name - just bold it.
- NEVER editorialize or pitch the product ("worth grabbing", "you're about
  due", "don't miss out", product features/qualities/ingredients). State
  facts only - you are not selling anything on the brand's behalf.
- Output nothing but the message itself - no preamble, no explanation.
"""


def _deal_prompt_block(deal: DealAlert) -> str:
    lines = [
        f"Item: {deal.title}",
        f"Product URL: {deal.product_url or '(none)'}",
        f"Current price: ${deal.current_price:.2f}",
        f"Savings: ${deal.savings:.2f}",
        f"Reorder window: {deal.window_start} to {deal.window_end}",
    ]
    if deal.last_paid_price is not None:
        lines.insert(3, f"You paid last time: ${deal.last_paid_price:.2f}")
    return "\n".join(lines)


class ClaudeAlertComposer:
    """Composes one proactive deal-alert Telegram message with a live Claude
    completion, covering one or more deals.

    Satisfies the `AlertComposer` protocol. Every fact in the prompt (price,
    savings, title, product URL, last-paid price, window) is already-real
    `ShoppingEngine`/catalog output - the LLM only ever rephrases those facts
    into the locked message shape, it never decides what the deal is or
    invents a number itself. The cart-add link/button is attached separately
    by the scheduler, not by this composer.
    """

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self._client = client or anthropic.Anthropic()

    def compose(self, deals: list[DealAlert]) -> str:
        prompt = "\n\n".join(_deal_prompt_block(d) for d in deals)
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=512,
            system=_ALERT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return next(block.text for block in response.content if block.type == "text")
