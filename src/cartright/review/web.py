from __future__ import annotations

from fastapi import APIRouter, Query, Response

from cartright.ratelimit import RateLimiter
from cartright.review.render import render_review
from cartright.review_links import verify_review_token
from cartright.shopping_engine import ShoppingEngine

# Most a single /review request will ever legitimately carry (a reorder cart is
# a handful of items). A higher count is either a mistake or an attempt to
# amplify one request into many walmart.io calls, so it's rejected.
DEFAULT_MAX_REVIEW_ITEMS = 25


def review_router(
    engine: ShoppingEngine,
    *,
    token_secret: str | None = None,
    max_items: int = DEFAULT_MAX_REVIEW_ITEMS,
    rate_limiter: RateLimiter | None = None,
) -> APIRouter:
    """Routes for the review-order surface, kept separate from the SMS module.

    `/review` is publicly reachable and turns each item into a real walmart.io
    call, so it is guarded - in this order, all *before* any pricing call - by a
    rate limit, an item-count cap, and (when `token_secret` is set) a signed,
    non-expired link token. A rejected request makes zero walmart.io calls.
    """
    limiter = rate_limiter or RateLimiter(max_requests=60, window_seconds=60.0)
    router = APIRouter()

    @router.get("/review")
    def review(
        item: list[str] = Query(default_factory=list),
        exp: int | None = None,
        token: str | None = None,
    ) -> Response:
        if not limiter.allow():
            return Response(status_code=429, content="rate limit exceeded")
        if len(item) > max_items:
            return Response(status_code=400, content=f"too many items (max {max_items})")
        if token_secret is not None:
            if (
                token is None
                or exp is None
                or not verify_review_token(item, exp, token, token_secret)
            ):
                return Response(status_code=403, content="invalid or expired review link")
        cart = engine.buildCart(item)
        return Response(content=render_review(cart), media_type="text/html")

    return router
