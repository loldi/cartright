from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI, Request, Response

from cartright.interaction.conversation import handle_inbound_preference
from cartright.llm.preferences import PreferenceParser
from cartright.preflight import readiness
from cartright.review.web import review_router
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import TwilioAdapter

_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _public_url(request: Request) -> str:
    """Reconstruct the URL Twilio signed, honoring proxy headers.

    Behind a host like Render the internal scheme/host differ from the public
    https URL Twilio actually POSTed to, and the signature is computed over that
    public URL - so prefer the forwarded headers when present.
    """
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = (
        request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    )
    url = f"{proto}://{host}{request.url.path}"
    return f"{url}?{request.url.query}" if request.url.query else url


def _twilio_signature_ok(
    auth_token: str | None, request: Request, form: Mapping[str, object]
) -> bool:
    """Validate X-Twilio-Signature. Fail-closed: no token or no signature -> False."""
    signature = request.headers.get("X-Twilio-Signature", "")
    if not auth_token or not signature:
        return False
    from twilio.request_validator import RequestValidator  # type: ignore[import-untyped]

    params = {key: str(value) for key, value in form.items()}
    validator = RequestValidator(auth_token)
    return bool(validator.validate(_public_url(request), params, signature))


def create_app(
    *,
    parser: PreferenceParser,
    engine: ShoppingEngine,
    twilio: TwilioAdapter,
    user_number: str,
    twilio_auth_token: str | None = None,
    validate_twilio_signature: bool = True,
    review_token_secret: str | None = None,
) -> FastAPI:
    """Build the Cartright web app wired to the given dependencies.

    Production passes real adapters; tests pass fakes satisfying the same
    interfaces. `user_number` is the single private number this instance serves
    - inbound SMS from anyone else is ignored.

    `validate_twilio_signature` defaults to on (fail-closed): inbound `/sms`
    requests must carry a valid `X-Twilio-Signature` computed with
    `twilio_auth_token`, or they are rejected with 403. Local/test callers can
    pass `validate_twilio_signature=False` to bypass it.
    """
    app = FastAPI(title="Cartright")

    @app.get("/health")
    def health() -> dict[str, object]:
        """Liveness + a secret-free readiness report of which subsystems are
        configured. Booleans only, derived from `run_doctor_checks` - this never
        echoes a secret value and never makes a live call."""
        return {"status": "ok", **readiness(os.environ)}

    @app.post("/sms")
    async def inbound_sms(request: Request) -> Response:
        form = await request.form()
        if validate_twilio_signature and not _twilio_signature_ok(twilio_auth_token, request, form):
            return Response(status_code=403, content="invalid Twilio signature")
        sender = str(form.get("From", ""))
        body = str(form.get("Body", ""))
        if sender == user_number:
            handle_inbound_preference(body, to=sender, parser=parser, engine=engine, twilio=twilio)
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    # The review-order UI is a separate surface; compose its routes in here.
    app.include_router(review_router(engine, token_secret=review_token_secret))

    return app
