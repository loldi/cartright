from __future__ import annotations

from fastapi import APIRouter, Query, Response

from cartright.review.render import render_review
from cartright.shopping_engine import ShoppingEngine


def review_router(engine: ShoppingEngine) -> APIRouter:
    """Routes for the review-order surface, kept separate from the SMS module."""
    router = APIRouter()

    @router.get("/review")
    def review(item: list[str] = Query(default_factory=list)) -> Response:
        cart = engine.buildCart(item)
        return Response(content=render_review(cart), media_type="text/html")

    return router
