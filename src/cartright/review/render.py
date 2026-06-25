from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cartright.shopping_engine.pricing import Cart

_TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)

# Stub destination for now: Slice 5 (#7) replaces this with a real Walmart
# cart/checkout deep link built from the cart contents.
STUB_CTA_URL = "https://www.walmart.com/cart"


def render_review(cart: Cart, cta_url: str = STUB_CTA_URL) -> str:
    """Render a buildCart() result as a server-rendered itemized review page.

    A pure rendering layer: cart data in, HTML out. No live data, no purchase
    is ever submitted here - the CTA only links the user onward.
    """
    template = _env.get_template("review.html")
    return template.render(cart=cart, cta_url=cta_url)
