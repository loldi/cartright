"""Slice 7: the real walmart.io catalog/pricing adapter.

Every request is served by an in-process `httpx.MockTransport`, so no test here
ever touches a live walmart.io endpoint. Auth signing is exercised against an
ephemeral RSA keypair generated per test.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from cartright.shopping_engine.adapters.walmart import (
    WalmartCatalogPricingAdapter,
    WalmartCredentials,
)

BASE_URL = "https://walmart.test/v2"


def _credentials() -> tuple[WalmartCredentials, rsa.RSAPublicKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    creds = WalmartCredentials(
        consumer_id="11111111-2222-3333-4444-555555555555",
        key_version="1",
        private_key=key,
        publisher_id="pub-123",
    )
    return creds, key.public_key()


def _make_adapter(
    handler: Any, creds: WalmartCredentials | None = None
) -> WalmartCatalogPricingAdapter:
    creds = creds or _credentials()[0]
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WalmartCatalogPricingAdapter(creds, client=client, base_url=BASE_URL)


def _item(**overrides: Any) -> dict[str, Any]:
    item = {
        "itemId": 10295020,
        "name": "Great Value Paper Towels, 6 Double Rolls",
        "salePrice": 8.97,
        "msrp": 10.97,
        "stock": "Available",
        "availableOnline": True,
    }
    item.update(overrides)
    return item


def test_maps_item_fields_onto_the_engine_price_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_item()]})

    price = _make_adapter(handler).get_price("10295020")

    assert price == {
        "item_id": "10295020",
        "title": "Great Value Paper Towels, 6 Double Rolls",
        "in_stock": True,
        "price": 8.97,
        "was_price": 10.97,
    }


def test_sends_all_four_auth_headers_with_a_verifiable_signature() -> None:
    creds, public_key = _credentials()
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"items": [_item()]})

    _make_adapter(handler, creds).get_price("10295020")

    assert captured["wm_consumer.id"] == creds.consumer_id
    assert captured["wm_sec.key_version"] == "1"
    timestamp = captured["wm_consumer.intimestamp"]
    assert timestamp.isdigit()

    # Recompute the canonical string and verify the signature the adapter sent.
    canonical = f"{creds.consumer_id}\n{timestamp}\n1\n".encode()
    public_key.verify(
        base64.b64decode(captured["wm_sec.auth_signature"]),
        canonical,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )  # raises InvalidSignature if wrong


def test_wrong_canonical_string_fails_verification() -> None:
    """Guards the signature test above: a tampered payload must NOT verify."""
    creds, public_key = _credentials()
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"items": [_item()]})

    _make_adapter(handler, creds).get_price("10295020")

    with pytest.raises(InvalidSignature):
        public_key.verify(
            base64.b64decode(captured["wm_sec.auth_signature"]),
            b"not-the-signed-string",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )


def test_includes_publisher_id_param_when_set() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["publisherId"] = request.url.params.get("publisherId", "")
        return httpx.Response(200, json={"items": [_item()]})

    _make_adapter(handler).get_price("10295020")

    assert seen["publisherId"] == "pub-123"


def test_out_of_stock_item_is_reported_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_item(stock="Not available")]})

    price = _make_adapter(handler).get_price("10295020")

    assert price["in_stock"] is False


def test_installment_only_item_with_no_sale_price_is_unavailable_and_unpriced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        item = _item()
        del item["salePrice"]
        return httpx.Response(200, json={"items": [item]})

    price = _make_adapter(handler).get_price("10295020")

    assert price["in_stock"] is False
    assert "price" not in price


def test_handles_a_bare_single_item_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_item())

    price = _make_adapter(handler).get_price("10295020")

    assert price["item_id"] == "10295020"
    assert price["price"] == 8.97


def test_invalid_item_id_returns_empty_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": [{"message": "Invalid itemId", "code": 4002}]})

    assert _make_adapter(handler).get_price("nope") == {}


def test_empty_items_list_returns_empty_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    assert _make_adapter(handler).get_price("10295020") == {}


def test_server_error_is_surfaced_not_swallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": [{"message": "boom", "code": 5000}]})

    with pytest.raises(httpx.HTTPStatusError):
        _make_adapter(handler).get_price("10295020")


def test_from_env_loads_pem_key_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    monkeypatch.setenv("WM_PRIVATE_KEY", pem)
    monkeypatch.setenv("WM_CONSUMER_ID", "abc")
    monkeypatch.setenv("WM_KEY_VERSION", "2")
    monkeypatch.setenv("WM_PUBLISHER_ID", "pub-xyz")

    creds = WalmartCredentials.from_env()

    assert creds.consumer_id == "abc"
    assert creds.key_version == "2"
    assert creds.publisher_id == "pub-xyz"
    assert isinstance(creds.private_key, rsa.RSAPrivateKey)


def test_real_adapter_drops_into_the_engine_unchanged() -> None:
    """The whole point: ShoppingEngine doesn't know which adapter it's holding."""
    from cartright.shopping_engine import ShoppingEngine
    from cartright.shopping_engine.adapters.fixtures import FixtureOrderHistoryAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_item()]})

    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(),
        catalog=_make_adapter(handler),
    )

    cart = engine.buildCart(["10295020"])

    assert len(cart.items) == 1
    assert cart.items[0].unit_price == 8.97
    assert cart.total == 8.97
