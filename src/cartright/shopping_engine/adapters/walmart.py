from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from cartright.shopping_engine.adapters.base import CatalogPricingAdapter

# Publicly documented Walmart Affiliate Marketing API base path. Everything this
# adapter touches lives under here - no non-public Walmart endpoints, systems, or
# internal knowledge anywhere in this code.
DEFAULT_BASE_URL = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2"

# Walmart's documented out-of-stock sentinel in the `stock` field; the other
# documented values (Available / Limited Supply / Last few items) all mean buyable.
_OUT_OF_STOCK = "Not available"


@dataclass(frozen=True)
class WalmartCredentials:
    """The four things every walmart.io call needs to authenticate.

    `private_key` is the already-loaded RSA key object, not raw bytes, so signing
    is trivially testable with an ephemeral key and never reads a file itself.
    """

    consumer_id: str
    key_version: str
    private_key: rsa.RSAPrivateKey
    publisher_id: str | None = None

    @classmethod
    def from_env(cls) -> WalmartCredentials:
        """Load credentials from the environment for production wiring.

        `WM_PRIVATE_KEY` holds the PKCS#8 RSA private key whose public half was
        uploaded to the Walmart developer portal, in either form the docs/tools
        produce: a PEM block (`-----BEGIN PRIVATE KEY-----`) or the raw
        base64-encoded DER the docs literally describe ("PKCS#8, base64-encoded").
        """
        key = _load_private_key(os.environ["WM_PRIVATE_KEY"])
        return cls(
            consumer_id=os.environ["WM_CONSUMER_ID"],
            key_version=os.environ.get("WM_KEY_VERSION", "1"),
            private_key=key,
            publisher_id=os.environ.get("WM_PUBLISHER_ID"),
        )


def _load_private_key(raw: str) -> rsa.RSAPrivateKey:
    """Parse the configured private key, accepting PEM or base64 DER PKCS#8."""
    raw = raw.strip()
    if "-----BEGIN" in raw:
        key = serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
    else:
        # Raw base64-encoded DER, as the docs describe the key ("base64-encoded").
        key = serialization.load_der_private_key(base64.b64decode(raw), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("WM_PRIVATE_KEY must be an RSA private key")
    return key


def _sign(consumer_id: str, timestamp_ms: str, key_version: str, key: rsa.RSAPrivateKey) -> str:
    """Build the WM_SEC.AUTH_SIGNATURE value.

    Mirrors the documented Java reference: sort the three header values by key
    name, join each `value + "\\n"`, then sign the UTF-8 bytes with
    SHA256withRSA (RSASSA-PKCS1-v1_5 + SHA-256) and base64-encode the result.
    """
    fields = {
        "WM_CONSUMER.ID": consumer_id,
        "WM_CONSUMER.INTIMESTAMP": timestamp_ms,
        "WM_SEC.KEY_VERSION": key_version,
    }
    canonical = "".join(f"{fields[name]}\n" for name in sorted(fields))
    signature = key.sign(canonical.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


class WalmartCatalogPricingAdapter(CatalogPricingAdapter):
    """Real price/availability lookups via the walmart.io Product Lookup endpoint.

    Satisfies `CatalogPricingAdapter`, so it drops straight into `ShoppingEngine`
    in place of the fixture. The `httpx.Client` is injectable: tests pass one
    backed by `httpx.MockTransport` so no test ever touches a live walmart.io
    endpoint.
    """

    def __init__(
        self,
        credentials: WalmartCredentials,
        *,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10.0)

    @classmethod
    def from_env(cls) -> WalmartCatalogPricingAdapter:
        """Production constructor: real credentials from the environment."""
        return cls(WalmartCredentials.from_env())

    def _auth_headers(self) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        creds = self._credentials
        return {
            "WM_SEC.KEY_VERSION": creds.key_version,
            "WM_CONSUMER.ID": creds.consumer_id,
            "WM_CONSUMER.INTIMESTAMP": timestamp_ms,
            "WM_SEC.AUTH_SIGNATURE": _sign(
                creds.consumer_id, timestamp_ms, creds.key_version, creds.private_key
            ),
            "Accept": "application/json",
        }

    def get_price(self, item_id: str) -> dict[str, Any]:
        """Return the engine's price shape for an item, or `{}` if unavailable.

        An empty dict (unknown / invalid / item-level error) is the same signal
        the fixture adapter gives, which `evaluate_deal`/`build_cart` already read
        as "not buyable". Server-side (5xx) failures are surfaced, not hidden.
        """
        params = {}
        if self._credentials.publisher_id is not None:
            params["publisherId"] = self._credentials.publisher_id
        response = self._client.get(
            f"{self._base_url}/items/{item_id}",
            headers=self._auth_headers(),
            params=params,
        )
        if response.status_code >= 500:
            response.raise_for_status()
        if response.status_code != 200:
            # 400/403/404 - invalid id, not found, item-level rejection: no price.
            return {}
        item = _first_item(response.json())
        if item is None:
            return {}
        return _to_price(item, item_id)


def _first_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the single item out of a Product Lookup response.

    `/items` returns `{items: [...]}`; `/items/{id}` may return the bare item.
    Handle both rather than assume one shape.
    """
    items = payload.get("items")
    if isinstance(items, list):
        return items[0] if items else None
    if "itemId" in payload:
        return payload
    return None


def _to_price(item: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Map a walmart.io `full` item onto the engine's price dict.

    `salePrice` is the current price and `msrp` the reference to discount from.
    An item with no `salePrice` (e.g. installment-only) is not buyable in this
    model, so it is reported out of stock rather than priced. `substitution` is
    intentionally never set here: it is a Cartright-side concept, and the
    documented path to a real substitute is the Post Browsed Products endpoint,
    left for a later slice (and moot until a shopper grants substitution anyway).
    """
    sale_price = item.get("salePrice")
    available = bool(item.get("availableOnline", True))
    in_stock = available and item.get("stock") != _OUT_OF_STOCK and sale_price is not None

    price: dict[str, Any] = {
        "item_id": str(item.get("itemId", item_id)),
        "title": item.get("name", str(item_id)),
        "in_stock": in_stock,
    }
    if sale_price is not None:
        price["price"] = float(sale_price)
    msrp = item.get("msrp")
    if msrp is not None:
        price["was_price"] = float(msrp)
    product_url = item.get("productUrl")
    if product_url is not None:
        price["product_url"] = str(product_url)
    return price
