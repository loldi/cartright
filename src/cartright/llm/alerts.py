from __future__ import annotations

from typing import Protocol

from cartright.shopping_engine.engine import ReorderCandidate
from cartright.shopping_engine.pricing import DealEvaluation


class AlertComposer(Protocol):
    """Turns an already-evaluated, real deal into a proactive alert SMS.

    The production implementation drives this with a live Claude completion
    constrained to the real facts handed in (price, savings, title, review
    link); tests supply a fake that returns canned text, so no real LLM call
    ever happens in the test path.
    """

    def compose(
        self, candidate: ReorderCandidate, deal: DealEvaluation, review_url: str
    ) -> str: ...
