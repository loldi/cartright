from __future__ import annotations

import time
from datetime import date

from cartright.llm.alerts import AlertComposer
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import TwilioAdapter
from cartright.shopping_engine.engine import ReorderCandidate


def _in_window(candidate: ReorderCandidate, today: date) -> bool:
    start = date.fromisoformat(candidate.window_start)
    end = date.fromisoformat(candidate.window_end)
    return start <= today <= end


def run_alert_cycle(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    twilio: TwilioAdapter,
    user_number: str,
    review_base_url: str,
    today: date | None = None,
) -> list[str]:
    """Run one pass of the proactive personalization loop.

    For every reorder candidate currently inside its predicted window, checks
    for a real deal and only then sends an SMS alert linking to that item's
    review page. Candidates outside their window are never even deal-checked
    - the resulting silence is the personalization, not a side effect of it.
    Returns the bodies of any SMS sent, for tests/observability.
    """
    today = today or date.today()
    sent: list[str] = []
    for candidate in engine.getReorderCandidates():
        if not _in_window(candidate, today):
            continue
        deal = engine.evaluateDeal(candidate.item_id)
        if not deal.is_deal:
            continue
        review_url = f"{review_base_url}?item={candidate.item_id}"
        body = composer.compose(candidate, deal, review_url)
        twilio.send_sms(to=user_number, body=body)
        sent.append(body)
    return sent


def run_forever(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    twilio: TwilioAdapter,
    user_number: str,
    review_base_url: str,
    interval_seconds: int = 3600,
) -> None:  # pragma: no cover - thin production loop, no decision logic of its own
    """Production entrypoint: run `run_alert_cycle` on a fixed interval forever."""
    while True:
        run_alert_cycle(
            engine=engine,
            composer=composer,
            twilio=twilio,
            user_number=user_number,
            review_base_url=review_base_url,
        )
        time.sleep(interval_seconds)
