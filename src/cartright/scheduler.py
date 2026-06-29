from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from cartright.llm.alerts import AlertComposer
from cartright.review_links import build_review_url
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import Messenger
from cartright.shopping_engine.engine import ReorderCandidate


@dataclass(frozen=True)
class AlertOutcome:
    """What the cycle decided for one reorder candidate, for reporting."""

    item_id: str
    title: str
    sent: bool
    reason: str
    body: str | None  # the message body, when one was sent


def _in_window(candidate: ReorderCandidate, today: date) -> bool:
    start = date.fromisoformat(candidate.window_start)
    end = date.fromisoformat(candidate.window_end)
    return start <= today <= end


def run_alert_cycle_detailed(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    messenger: Messenger,
    user_chat_id: str,
    review_base_url: str,
    review_token_secret: str | None = None,
    today: date | None = None,
) -> list[AlertOutcome]:
    """Run one pass of the proactive loop, returning a per-candidate report.

    For every reorder candidate inside its predicted window, checks for a real
    deal and only then sends a message alert linking to that item's review page.
    Candidates outside their window are never even deal-checked - the resulting
    silence is the personalization, not a side effect of it.
    """
    today = today or date.today()
    outcomes: list[AlertOutcome] = []

    def _record(candidate: ReorderCandidate, outcome: AlertOutcome) -> None:
        engine.recordDecision(
            item_id=outcome.item_id,
            title=outcome.title,
            sent=outcome.sent,
            reason=outcome.reason,
            body=outcome.body,
            window_start=candidate.window_start,
            window_end=candidate.window_end,
        )
        outcomes.append(outcome)

    for candidate in engine.getReorderCandidates():
        if not _in_window(candidate, today):
            _record(
                candidate,
                AlertOutcome(
                    candidate.item_id,
                    candidate.title,
                    False,
                    f"outside reorder window ({candidate.window_start}..{candidate.window_end})",
                    None,
                ),
            )
            continue
        if engine.hasAlertedInWindow(
            candidate.item_id, candidate.window_start, candidate.window_end
        ):
            _record(
                candidate,
                AlertOutcome(
                    candidate.item_id,
                    candidate.title,
                    False,
                    "already alerted for this reorder window - not resending",
                    None,
                ),
            )
            continue
        deal = engine.evaluateDeal(candidate.item_id)
        if not deal.is_deal:
            _record(
                candidate,
                AlertOutcome(
                    candidate.item_id, candidate.title, False, "in window, but no real deal", None
                ),
            )
            continue
        review_url = build_review_url(
            review_base_url, candidate.item_id, secret=review_token_secret
        )
        body = composer.compose(candidate, deal, review_url)
        messenger.send_message(to=user_chat_id, body=body)
        _record(
            candidate,
            AlertOutcome(
                candidate.item_id, candidate.title, True, f"deal: ${deal.savings:.2f} off", body
            ),
        )
    return outcomes


def run_alert_cycle(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    messenger: Messenger,
    user_chat_id: str,
    review_base_url: str,
    review_token_secret: str | None = None,
    today: date | None = None,
) -> list[str]:
    """Run one cycle and return just the bodies of any message sent.

    A thin wrapper over `run_alert_cycle_detailed` for the production loop and
    existing callers; the detailed variant carries the skip reasons that the
    `cartright alert-once` command surfaces.
    """
    return [
        o.body
        for o in run_alert_cycle_detailed(
            engine=engine,
            composer=composer,
            messenger=messenger,
            user_chat_id=user_chat_id,
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
    messenger: Messenger,
    user_chat_id: str,
    review_base_url: str,
    review_token_secret: str | None = None,
    interval_seconds: int = 3600,
) -> None:  # pragma: no cover - thin production loop, no decision logic of its own
    """Production entrypoint: run `run_alert_cycle` on a fixed interval forever."""
    while True:
        run_alert_cycle(
            engine=engine,
            composer=composer,
            messenger=messenger,
            user_chat_id=user_chat_id,
            review_base_url=review_base_url,
            review_token_secret=review_token_secret,
        )
        time.sleep(interval_seconds)
