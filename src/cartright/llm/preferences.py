from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ParsedPreference:
    """A structured preference the LLM extracted from a casual text message."""

    item_id: str
    attributes: dict[str, Any]
    confirmation: str


class PreferenceParser(Protocol):
    """Turns a casual natural-language preference statement into structure.

    The production implementation drives this with a live Claude completion;
    tests supply a fake that returns canned output, so no real LLM call ever
    happens in the test path.
    """

    def parse(self, text: str) -> ParsedPreference: ...
