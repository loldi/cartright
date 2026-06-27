from __future__ import annotations

import os

from fastapi import FastAPI, Form, Response

from cartright.interaction.conversation import handle_inbound_preference
from cartright.llm.preferences import PreferenceParser
from cartright.preflight import readiness
from cartright.review.web import review_router
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import TwilioAdapter

_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def create_app(
    *,
    parser: PreferenceParser,
    engine: ShoppingEngine,
    twilio: TwilioAdapter,
    user_number: str,
) -> FastAPI:
    """Build the Cartright web app wired to the given dependencies.

    Production passes real adapters; tests pass fakes satisfying the same
    interfaces. `user_number` is the single private number this instance serves
    - inbound SMS from anyone else is ignored.
    """
    app = FastAPI(title="Cartright")

    @app.get("/health")
    def health() -> dict[str, object]:
        """Liveness + a secret-free readiness report of which subsystems are
        configured. Booleans only, derived from `run_doctor_checks` - this never
        echoes a secret value and never makes a live call."""
        return {"status": "ok", **readiness(os.environ)}

    @app.post("/sms")
    def inbound_sms(From: str = Form(...), Body: str = Form(...)) -> Response:
        if From == user_number:
            handle_inbound_preference(Body, to=From, parser=parser, engine=engine, twilio=twilio)
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    # The review-order UI is a separate surface; compose its routes in here.
    app.include_router(review_router(engine))

    return app
