"""Signed, expiring review links, shared by the alert loop and the /review route.

The scheduler builds an alert's review URL with `build_review_url`; the `/review`
endpoint verifies the token with `verify_review_token` before doing any work. An
HMAC over the (sorted) item ids + an expiry means only links Cartright actually
generated resolve - a forged or stale `?item=...` is rejected before a single
walmart.io call is made.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Sequence
from urllib.parse import urlencode

# How long a review link stays valid. A week comfortably covers a reorder window
# plus the user taking their time to act on the text.
REVIEW_TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _canonical(items: Sequence[str], exp: int) -> bytes:
    # Sort so item order in the URL doesn't change the signature.
    return ("|".join(sorted(items)) + f"|{exp}").encode("utf-8")


def sign_review_token(items: Sequence[str], exp: int, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _canonical(items, exp), hashlib.sha256).hexdigest()


def verify_review_token(
    items: Sequence[str], exp: int, token: str, secret: str, *, now: int | None = None
) -> bool:
    """True only if the token matches these items and hasn't expired."""
    current = now if now is not None else int(time.time())
    if exp < current:
        return False
    expected = sign_review_token(items, exp, secret)
    return hmac.compare_digest(expected, token)


def build_review_url(
    review_base_url: str,
    item_ids: str | Sequence[str],
    *,
    secret: str | None = None,
    ttl_seconds: int = REVIEW_TOKEN_TTL_SECONDS,
    now: int | None = None,
) -> str:
    """Build a review-page link, signed when a `secret` is supplied.

    Without a secret the link is the plain `?item=<id>` form (the local/unsigned
    fallback); with one it gains `&exp=<unix>&token=<hmac>` that `/review`
    verifies. Accepts a single id or a list.
    """
    items = [item_ids] if isinstance(item_ids, str) else list(item_ids)
    params: list[tuple[str, str]] = [("item", i) for i in items]
    if secret:
        current = now if now is not None else int(time.time())
        exp = current + ttl_seconds
        params.append(("exp", str(exp)))
        params.append(("token", sign_review_token(items, exp, secret)))
    return f"{review_base_url}?{urlencode(params)}"
