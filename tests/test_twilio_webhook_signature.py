"""GL-6: the /sms webhook validates X-Twilio-Signature (fail-closed).

No real Twilio call: signatures are computed locally with Twilio's own
`RequestValidator` over a shared test auth token, exactly as Twilio would.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator  # type: ignore[import-untyped]

from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureOrderHistoryAdapter,
    FixtureTwilioAdapter,
)

USER = "+15555550123"
AUTH_TOKEN = "test-auth-token-abc123"
SMS_URL = "http://testserver/sms"


class _Parser:
    def parse(self, text: str) -> ParsedPreference:
        return ParsedPreference(item_id="coffee", attributes={}, confirmation="Got it.")


def _engine() -> ShoppingEngine:
    return ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(), catalog=FixtureCatalogPricingAdapter()
    )


def _signed_client(
    engine: ShoppingEngine, twilio: FixtureTwilioAdapter, *, validate: bool = True
) -> TestClient:
    app = create_app(
        parser=_Parser(),
        engine=engine,
        twilio=twilio,
        user_number=USER,
        twilio_auth_token=AUTH_TOKEN,
        validate_twilio_signature=validate,
    )
    return TestClient(app)


def _signature(params: dict[str, Any]) -> str:
    return str(RequestValidator(AUTH_TOKEN).compute_signature(SMS_URL, params))


def test_valid_signature_is_accepted_and_records_the_preference() -> None:
    engine, twilio = _engine(), FixtureTwilioAdapter()
    client = _signed_client(engine, twilio)
    params = {"From": USER, "Body": "I only drink Peet's"}

    response = client.post("/sms", data=params, headers={"X-Twilio-Signature": _signature(params)})

    assert response.status_code == 200
    assert engine.getPreference("coffee") is not None
    assert twilio.sent == [{"to": USER, "body": "Got it."}]


def test_missing_signature_is_rejected_fail_closed() -> None:
    engine, twilio = _engine(), FixtureTwilioAdapter()
    client = _signed_client(engine, twilio)

    response = client.post("/sms", data={"From": USER, "Body": "hi"})

    assert response.status_code == 403
    assert engine.getPreference("coffee") is None
    assert twilio.sent == []


def test_bad_signature_is_rejected() -> None:
    engine, twilio = _engine(), FixtureTwilioAdapter()
    client = _signed_client(engine, twilio)

    response = client.post(
        "/sms",
        data={"From": USER, "Body": "hi"},
        headers={"X-Twilio-Signature": "not-a-valid-signature"},
    )

    assert response.status_code == 403
    assert engine.getPreference("coffee") is None


def test_valid_signature_from_wrong_number_is_still_ignored() -> None:
    engine, twilio = _engine(), FixtureTwilioAdapter()
    client = _signed_client(engine, twilio)
    params = {"From": "+19998887777", "Body": "I only drink Peet's"}

    response = client.post("/sms", data=params, headers={"X-Twilio-Signature": _signature(params)})

    # Signature is valid, so it's not a 403 - but the sender isn't the served
    # number, so nothing is recorded.
    assert response.status_code == 200
    assert engine.getPreference("coffee") is None
    assert twilio.sent == []


def test_validation_can_be_disabled_for_local_use() -> None:
    engine, twilio = _engine(), FixtureTwilioAdapter()
    client = _signed_client(engine, twilio, validate=False)

    response = client.post("/sms", data={"From": USER, "Body": "hi"})

    assert response.status_code == 200
    assert engine.getPreference("coffee") is not None
