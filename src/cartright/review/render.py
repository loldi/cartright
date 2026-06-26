from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cartright.shopping_engine.pricing import Cart, build_walmart_cart_url

_TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def render_review(cart: Cart, cta_url: str | None = None) -> str:
    """Render a buildCart() result as a server-rendered itemized review page.

    A pure rendering layer: cart data in, HTML out. No live data, no purchase
    is ever submitted here - the CTA only links the user onward to their own
    real Walmart cart. `cta_url` is overridable for tests; production callers
    leave it unset so it's derived from the cart contents.
    """
    template = _env.get_template("review.html")
    return template.render(cart=cart, cta_url=cta_url or build_walmart_cart_url(cart))
