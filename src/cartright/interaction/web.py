from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Request, Response

from cartright.interaction.conversation import handle_inbound_preference
from cartright.llm.preferences import PreferenceParser
from cartright.preflight import readiness
from cartright.review.web import review_router
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import Messenger

_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _webhook_secret_ok(expected: str | None, request: Request) -> bool:
    """Validate the Telegram webhook secret token. Fail-closed.

    Telegram echoes the `secret_token` configured via `setWebhook` in the
    `X-Telegram-Bot-Api-Secret-Token` header on every update. No configured
    secret, or a missing/wrong header, means reject - a constant-time compare
    so the check leaks no timing signal.
    """
    got = request.headers.get(_SECRET_HEADER, "")
    if not expected or not got:
        return False
    return hmac.compare_digest(got, expected)


def create_app(
    *,
    parser: PreferenceParser,
    engine: ShoppingEngine,
    messenger: Messenger,
    user_chat_id: str,
    webhook_secret: str | None = None,
    validate_webhook: bool = True,
    review_token_secret: str | None = None,
) -> FastAPI:
    """Build the Cartright web app wired to the given dependencies.

    Production passes real adapters; tests pass fakes satisfying the same
    interfaces. `user_chat_id` is the single private Telegram chat this instance
    serves - an update from any other chat is ignored.

    `validate_webhook` defaults to on (fail-closed): inbound `/telegram` updates
    must carry the matching `X-Telegram-Bot-Api-Secret-Token`, or they are
    rejected with 403. Local/test callers can pass `validate_webhook=False`.
    """
    app = FastAPI(title="Cartright")

    @app.get("/health")
    def health() -> dict[str, object]:
        """Liveness + a secret-free readiness report of which subsystems are
        configured. Booleans only, derived from `run_doctor_checks` - this never
        echoes a secret value and never makes a live call."""
        return {"status": "ok", **readiness(os.environ)}

    @app.post("/telegram")
    async def inbound_telegram(request: Request) -> Response:
        if validate_webhook and not _webhook_secret_ok(webhook_secret, request):
            return Response(status_code=403, content="invalid webhook secret")
        update = await request.json()
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = str(message.get("text", ""))
        # Only the one private chat this instance serves; ignore everything else.
        if chat_id and chat_id == user_chat_id and text:
            handle_inbound_preference(
                text, to=chat_id, parser=parser, engine=engine, messenger=messenger
            )
        return Response(status_code=200)

    # The review-order UI is a separate surface; compose its routes in here.
    app.include_router(review_router(engine, token_secret=review_token_secret))

    return app
