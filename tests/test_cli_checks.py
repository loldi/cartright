"""GL-2/3/4: the live-seam check subcommands (catalog / orders / sms).

Each command takes an injected adapter so tests exercise it with fakes - a
walmart adapter backed by `httpx.MockTransport`, a real JSON-file order adapter
over a temp file, and a fake Twilio client. No test touches a live endpoint or
sends a real SMS. The error-output tests assert that secrets (the walmart
signature, a Twilio Account SID) never appear in what the command prints.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from cartright.cli import catalog_check, orders_check, sms_check
from cartright.shopping_engine.adapters.base import TwilioAdapter
from cartright.shopping_engine.adapters.order_history import JsonFileOrderHistoryAdapter
from cartright.shopping_engine.adapters.twilio_sms import TwilioSmsAdapter
from cartright.shopping_engine.adapters.walmart import (
    WalmartCatalogPricingAdapter,
    WalmartCredentials,
)

# ---- walmart catalog-check ------------------------------------------------


def _catalog_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> WalmartCatalogPricingAdapter:
    creds = WalmartCredentials(
        consumer_id="11111111-2222-3333-4444-555555555555",
        key_version="1",
        private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        publisher_id="pub-123",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WalmartCatalogPricingAdapter(creds, client=client, base_url="https://walmart.test/v2")


def test_catalog_check_prints_mapped_fields_on_success() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "itemId": 10295020,
                        "name": "Great Value Paper Towels",
                        "salePrice": 8.97,
                        "msrp": 10.97,
                        "stock": "Available",
                    }
                ]
            },
        )

    out = io.StringIO()
    code = catalog_check(_catalog_adapter(handler), "10295020", out=out)

    text = out.getvalue()
    assert code == 0
    assert "10295020" in text
    assert "Great Value Paper Towels" in text
    assert "8.97" in text


def test_catalog_check_reports_no_result_on_4xx() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": [{"message": "Invalid itemId", "code": 4002}]})

    out = io.StringIO()
    code = catalog_check(_catalog_adapter(handler), "nope", out=out)

    assert code == 1
    assert "no result" in out.getvalue().lower()


def test_catalog_check_handles_server_error_without_leaking_secrets() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": [{"message": "boom", "code": 5000}]})

    out = io.StringIO()
    code = catalog_check(_catalog_adapter(handler), "10295020", out=out)

    text = out.getvalue()
    assert code == 1
    assert "500" in text
    # Never echo the auth signature header / raw request.
    assert "WM_SEC" not in text
    assert "AUTH_SIGNATURE" not in text


# ---- orders-check ---------------------------------------------------------

_GOOD_ORDERS = [
    {"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-01"},
    {"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-11"},
    {"item_id": "37774610", "title": "Coffee", "ordered_at": "2026-06-02"},
]


def _orders_adapter(tmp_path: Path, data: object) -> JsonFileOrderHistoryAdapter:
    path = tmp_path / "orders.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return JsonFileOrderHistoryAdapter.from_file(path)


def test_orders_check_reports_count_and_candidates(tmp_path: Path) -> None:
    out = io.StringIO()
    code = orders_check(_orders_adapter(tmp_path, _GOOD_ORDERS), out=out)

    text = out.getvalue()
    assert code == 0
    assert "3" in text  # 3 order records
    # paper towels (2 orders) yields a reorder candidate; coffee (1) does not.
    assert "10295020" in text


def test_orders_check_flags_malformed_rows(tmp_path: Path) -> None:
    bad = [
        {"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-01"},
        {"item_id": "", "title": "missing id", "ordered_at": "2026-06-02"},
        {"item_id": "x", "title": "bad date", "ordered_at": "not-a-date"},
    ]
    out = io.StringIO()
    code = orders_check(_orders_adapter(tmp_path, bad), out=out)

    text = out.getvalue().lower()
    assert code == 1
    assert "row 1" in text  # zero-based index of the empty-id row
    assert "row 2" in text  # bad-date row


def test_orders_check_handles_empty_file(tmp_path: Path) -> None:
    out = io.StringIO()
    code = orders_check(_orders_adapter(tmp_path, []), out=out)

    assert code == 1
    assert "no orders" in out.getvalue().lower()


# ---- sms-check ------------------------------------------------------------


class _FakeMessages:
    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []

    def create(self, *, to: str, from_: str, body: str) -> None:
        self.created.append({"to": to, "from_": from_, "body": body})


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_sms_check_sends_one_message() -> None:
    client = _FakeClient()
    adapter = TwilioSmsAdapter(client, from_number="+15550001111")
    out = io.StringIO()

    code = sms_check(adapter, "+15555550123", out=out)

    assert code == 0
    assert len(client.messages.created) == 1
    assert client.messages.created[0]["to"] == "+15555550123"


class _BoomTwilio(TwilioAdapter):
    """A Twilio adapter whose send raises an error carrying a secret SID."""

    def send_sms(self, to: str, body: str) -> None:
        raise _FakeTwilioError()

    def receive_sms(self) -> list[dict[str, object]]:
        return []


class _FakeTwilioError(Exception):
    status = 401
    uri = "https://api.twilio.com/2010-04-01/Accounts/ACsecretsid12345/Messages.json"

    def __str__(self) -> str:
        return f"HTTP 401 error: {self.uri}"


def test_sms_check_error_output_never_leaks_account_sid() -> None:
    out = io.StringIO()
    code = sms_check(_BoomTwilio(), "+15555550123", out=out)

    text = out.getvalue()
    assert code == 1
    assert "ACsecretsid12345" not in text
    assert "api.twilio.com" not in text
    assert "401" in text  # status is fine to show
