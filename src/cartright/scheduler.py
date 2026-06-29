from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from cartright.llm.alerts import AlertComposer, DealAlert
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import Messenger
from cartright.shopping_engine.engine import ReorderCandidate
from cartright.shopping_engine.pricing import Cart, CartItem, build_walmart_cart_url


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


def _cart_url(deals: list[DealAlert]) -> str:
    cart = Cart(
        items=[
            CartItem(
                item_id=d.item_id,
                title=d.title,
                unit_price=d.current_price,
                quantity=1,
                line_total=d.current_price,
                substitution=None,
            )
            for d in deals
        ],
        total=round(sum(d.current_price for d in deals), 2),
    )
    return build_walmart_cart_url(cart)


def run_alert_cycle_detailed(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    messenger: Messenger,
    user_chat_id: str,
    today: date | None = None,
) -> list[AlertOutcome]:
    """Run one pass of the proactive loop, returning a per-candidate report.

    For every reorder candidate inside its predicted window, checks for a real
    deal. Candidates outside their window are never even deal-checked - the
    resulting silence is the personalization, not a side effect of it.

    All deal-bearing candidates found this cycle are sent as exactly **one**
    Telegram message (single-item or multi-item digest), not one alert per
    item - see PRD.md's "Alert message format" decision.
    """
    today = today or date.today()
    outcomes: list[AlertOutcome] = []
    # Each entry: the candidate, the fact bundle for the composer, and the
    # price (if any) a prior alert already quoted for this exact window -
    # needed after the send to write the right "why" into the decision log.
    to_alert: list[tuple[ReorderCandidate, DealAlert, float | None]] = []

    def _skip(candidate: ReorderCandidate, reason: str) -> None:
        engine.recordDecision(
            item_id=candidate.item_id,
            title=candidate.title,
            sent=False,
            reason=reason,
            body=None,
            window_start=candidate.window_start,
            window_end=candidate.window_end,
        )
        outcomes.append(AlertOutcome(candidate.item_id, candidate.title, False, reason, None))

    for candidate in engine.getReorderCandidates():
        if not _in_window(candidate, today):
            _skip(
                candidate,
                f"outside reorder window ({candidate.window_start}..{candidate.window_end})",
            )
            continue
        deal = engine.evaluateDeal(candidate.item_id)
        if not deal.is_deal:
            _skip(candidate, "in window, but no real deal")
            continue
        last_alerted = engine.lastAlertedPrice(
            candidate.item_id, candidate.window_start, candidate.window_end
        )
        assert deal.current_price is not None  # is_deal implies a current price
        if last_alerted is not None and deal.current_price >= last_alerted:
            _skip(candidate, f"already alerted at ${last_alerted:.2f} or better - not resending")
            continue
        deal_alert = DealAlert(
            item_id=candidate.item_id,
            title=candidate.title,
            product_url=deal.product_url,
            current_price=deal.current_price,
            last_paid_price=engine.lastPaidPrice(candidate.item_id),
            savings=deal.savings,
            window_start=candidate.window_start,
            window_end=candidate.window_end,
        )
        to_alert.append((candidate, deal_alert, last_alerted))

    if to_alert:
        deal_alerts = [d for _, d, _ in to_alert]
        try:
            body = composer.compose(deal_alerts)
            button_text = (
                "Add to Walmart cart →" if len(deal_alerts) == 1 else "Add all to Walmart cart →"
            )
            messenger.send_message(
                to=user_chat_id,
                body=body,
                parse_mode="HTML",
                button_text=button_text,
                button_url=_cart_url(deal_alerts),
            )
        except Exception as exc:  # noqa: BLE001 - surface per-item, never crash the cycle
            error_reason = f"send failed: {type(exc).__name__}"
            for candidate, _deal_alert, _ in to_alert:
                engine.recordDecision(
                    item_id=candidate.item_id,
                    title=candidate.title,
                    sent=False,
                    reason=error_reason,
                    body=None,
                    window_start=candidate.window_start,
                    window_end=candidate.window_end,
                )
                outcomes.append(
                    AlertOutcome(candidate.item_id, candidate.title, False, error_reason, None)
                )
            return outcomes
        for candidate, deal_alert, last_alerted in to_alert:
            reason = (
                f"deal: ${deal_alert.savings:.2f} off"
                if last_alerted is None
                else (
                    f"price dropped further to ${deal_alert.current_price:.2f} "
                    f"(was ${last_alerted:.2f})"
                )
            )
            engine.recordDecision(
                item_id=candidate.item_id,
                title=candidate.title,
                sent=True,
                reason=reason,
                body=body,
                window_start=candidate.window_start,
                window_end=candidate.window_end,
                price=deal_alert.current_price,
            )
            outcomes.append(AlertOutcome(candidate.item_id, candidate.title, True, reason, body))

    return outcomes


def run_alert_cycle(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    messenger: Messenger,
    user_chat_id: str,
    today: date | None = None,
) -> list[str]:
    """Run one cycle and return the distinct message bodies actually sent.

    A thin wrapper over `run_alert_cycle_detailed` for the production loop and
    existing callers. A cycle sends at most one combined message even when
    several candidates alert, so this dedupes rather than returning the same
    body once per item.
    """
    seen: set[str] = set()
    bodies: list[str] = []
    for o in run_alert_cycle_detailed(
        engine=engine,
        composer=composer,
        messenger=messenger,
        user_chat_id=user_chat_id,
        today=today,
    ):
        if o.sent and o.body is not None and o.body not in seen:
            seen.add(o.body)
            bodies.append(o.body)
    return bodies


def run_forever(
    *,
    engine: ShoppingEngine,
    composer: AlertComposer,
    messenger: Messenger,
    user_chat_id: str,
    interval_seconds: int = 3600,
) -> None:  # pragma: no cover - thin production loop, no decision logic of its own
    """Production entrypoint: run `run_alert_cycle` on a fixed interval forever."""
    while True:
        run_alert_cycle(
            engine=engine,
            composer=composer,
            messenger=messenger,
            user_chat_id=user_chat_id,
        )
        time.sleep(interval_seconds)
