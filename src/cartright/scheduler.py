from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from cartright.llm.alerts import AlertComposer
from cartright.review_links import build_review_url
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import TwilioAdapter
from cartright.shopping_engine.engine import ReorderCandidate


@dataclass(frozen=True)
class AlertOutcome:
    """What the cycle decided for one reorder candidate, for reporting."""

    item_id: str
    title: str
    sent: bool
    reason: str
    body: str | None  # the SMS body, when one was sent


def _in_window(candidate: ReorderCandidate, today: date) -> bool:
    start = date.fromisoformat(candidate.window_start)
    end = date.fromisoformat(candidate.window_end)
    return start <= today <= end


def run_alert_cycle_detailed(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    twilio: TwilioAdapter,
    user_number: str,
    review_base_url: str,
    review_token_secret: str | None = None,
    today: date | None = None,
) -> list[AlertOutcome]:
    """Run one pass of the proactive loop, returning a per-candidate report.

    For every reorder candidate inside its predicted window, checks for a real
    deal and only then sends an SMS alert linking to that item's review page.
    Candidates outside their window are never even deal-checked - the resulting
    silence is the personalization, not a side effect of it.
    """
    today = today or date.today()
    outcomes: list[AlertOutcome] = []
    for candidate in engine.getReorderCandidates():
        if not _in_window(candidate, today):
            outcomes.append(
                AlertOutcome(
                    candidate.item_id,
                    candidate.title,
                    False,
                    f"outside reorder window ({candidate.window_start}..{candidate.window_end})",
                    None,
                )
            )
            continue
        deal = engine.evaluateDeal(candidate.item_id)
        if not deal.is_deal:
            outcomes.append(
                AlertOutcome(
                    candidate.item_id, candidate.title, False, "in window, but no real deal", None
                )
            )
            continue
        review_url = build_review_url(
            review_base_url, candidate.item_id, secret=review_token_secret
        )
        body = composer.compose(candidate, deal, review_url)
        twilio.send_sms(to=user_number, body=body)
        outcomes.append(
            AlertOutcome(
                candidate.item_id, candidate.title, True, f"deal: ${deal.savings:.2f} off", body
            )
        )
    return outcomes


def run_alert_cycle(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    twilio: TwilioAdapter,
    user_number: str,
    review_base_url: str,
    review_token_secret: str | None = None,
    today: date | None = None,
) -> list[str]:
    """Run one cycle and return just the bodies of any SMS sent.

    A thin wrapper over `run_alert_cycle_detailed` for the production loop and
    existing callers; the detailed variant carries the skip reasons that the
    `cartright alert-once` command surfaces.
    """
    return [
        o.body
        for o in run_alert_cycle_detailed(
            engine=engine,
            composer=composer,
            twilio=twilio,
            user_number=user_number,
            review_base_url=review_base_url,
            review_token_secret=review_token_secret,
            today=today,
        )
        if o.sent and o.body is not None
    ]


def run_forever(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    twilio: TwilioAdapter,
    user_number: str,
    review_base_url: str,
    review_token_secret: str | None = None,
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
            review_token_secret=review_token_secret,
        )
        time.sleep(interval_seconds)
