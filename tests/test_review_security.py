"""Hardening #27: /review item cap, rate limit, and signed-token verification.

A spy catalog records every price lookup so each test can prove a *rejected*
request makes zero walmart.io calls. No live endpoint is touched.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cartright.ratelimit import RateLimiter
from cartright.review.web import review_router
from cartright.review_links import build_review_url, sign_review_token
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import CatalogPricingAdapter
from cartright.shopping_engine.adapters.fixtures import FixtureOrderHistoryAdapter

SECRET = "review-signing-secret"
ITEM = "10295020"


class _SpyCatalog(CatalogPricingAdapter):
    def __init__(self) -> None:
        self.queried: list[str] = []

    def get_price(self, item_id: str) -> dict[str, Any]:
        self.queried.append(item_id)
        return {"item_id": item_id, "title": "Paper Towels", "price": 8.97, "in_stock": True}


def _client(
    catalog: _SpyCatalog,
    *,
    token_secret: str | None = None,
    max_items: int = 25,
    rate_limiter: RateLimiter | None = None,
) -> TestClient:
    engine = ShoppingEngine(order_history=FixtureOrderHistoryAdapter(), catalog=catalog)
    app = FastAPI()
    app.include_router(
        review_router(
            engine, token_secret=token_secret, max_items=max_items, rate_limiter=rate_limiter
        )
    )
    return TestClient(app)


def test_unsigned_request_under_cap_still_renders_when_no_secret() -> None:
    catalog = _SpyCatalog()
    response = _client(catalog).get("/review", params={"item": ITEM})

    assert response.status_code == 200
    assert catalog.queried == [ITEM]


def test_oversized_item_list_is_rejected_without_pricing_anything() -> None:
    catalog = _SpyCatalog()
    client = _client(catalog, max_items=3)

    response = client.get("/review", params={"item": ["a", "b", "c", "d", "e"]})

    assert response.status_code == 400
    assert catalog.queried == []  # rejected before any walmart.io call


def test_rate_limit_returns_429_and_makes_no_call() -> None:
    catalog = _SpyCatalog()
    client = _client(catalog, rate_limiter=RateLimiter(max_requests=1, window_seconds=60.0))

    first = client.get("/review", params={"item": ITEM})
    second = client.get("/review", params={"item": ITEM})

    assert first.status_code == 200
    assert second.status_code == 429
    assert catalog.queried == [ITEM]  # only the first request priced anything


def test_valid_token_renders() -> None:
    catalog = _SpyCatalog()
    client = _client(catalog, token_secret=SECRET)
    url = build_review_url("/review", ITEM, secret=SECRET)

    response = client.get(url)

    assert response.status_code == 200
    assert catalog.queried == [ITEM]


def test_missing_token_is_rejected_without_pricing() -> None:
    catalog = _SpyCatalog()
    client = _client(catalog, token_secret=SECRET)

    response = client.get("/review", params={"item": ITEM})

    assert response.status_code == 403
    assert catalog.queried == []


def test_forged_token_is_rejected_without_pricing() -> None:
    catalog = _SpyCatalog()
    client = _client(catalog, token_secret=SECRET)

    response = client.get("/review", params={"item": ITEM, "exp": 9999999999, "token": "forged"})

    assert response.status_code == 403
    assert catalog.queried == []


def test_expired_token_is_rejected_without_pricing() -> None:
    catalog = _SpyCatalog()
    client = _client(catalog, token_secret=SECRET)
    expired = 1_000  # far in the past
    token = sign_review_token([ITEM], expired, SECRET)

    response = client.get("/review", params={"item": ITEM, "exp": expired, "token": token})

    assert response.status_code == 403
    assert catalog.queried == []


def test_token_for_other_items_does_not_authorize_these_items() -> None:
    """A token signed for item A can't be replayed to price items A+B."""
    catalog = _SpyCatalog()
    client = _client(catalog, token_secret=SECRET)
    url = build_review_url("/review", ITEM, secret=SECRET)  # signs [ITEM] only

    response = client.get(url + "&item=99999999")  # smuggle an extra item

    assert response.status_code == 403
    assert catalog.queried == []


def test_build_review_url_is_plain_without_a_secret() -> None:
    assert build_review_url("https://x.test/review", "abc") == "https://x.test/review?item=abc"


def test_build_review_url_signs_when_a_secret_is_given() -> None:
    url = build_review_url("https://x.test/review", "abc", secret="s3cr3t", now=1000)

    # Signed links carry the item, an expiry, and an HMAC token.
    assert url.startswith("https://x.test/review?item=abc&exp=")
    assert "token=" in url
