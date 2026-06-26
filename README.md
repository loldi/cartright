# Cartright

A texting-based personal shopping agent for Walmart. Cartright learns what you
reorder and when, watches for real deals inside each item's predicted reorder
window, and texts you only when something is genuinely worth your time. Every
purchase is approve-then-handoff: it builds a real, itemized cart and a
walmart.com deep link you tap yourself. It never checks out for you, and it
never substitutes a product unless you've explicitly granted substitution for
that item.

See [`PRD.md`](PRD.md) for full product scope and the implementation decisions
behind it.

## Architecture at a glance

- **`shopping_engine/`** — the deterministic core. `ShoppingEngine` is the single
  seam between the LLM layer and everything else (reorder cadence, deal
  evaluation, cart building, preferences). It owns its own SQLite store and talks
  to the outside world only through adapter interfaces.
- **`shopping_engine/adapters/`** — the seams to real-world data:
  - `CatalogPricingAdapter` — current price/availability. Production impl
    (`WalmartCatalogPricingAdapter`) is built **exclusively against publicly
    documented walmart.io Affiliate APIs** (Product Lookup for real-time
    price/stock). No non-public Walmart endpoints or internal knowledge.
  - `OrderHistoryAdapter` — past purchases. Production impl
    (`JsonFileOrderHistoryAdapter`) consumes a structured order-history JSON file
    (see below).
  - `TwilioAdapter` — SMS in/out.
- **`llm/`** — Claude-backed preference parsing and deal-alert composition.
- **`interaction/`**, **`review/`**, **`scheduler.py`** — the SMS webhook, the
  itemized review UI, and the proactive alert loop.

## Configuration (production)

The real adapters read their config from the environment:

| Variable | Used by | Purpose |
|---|---|---|
| `WM_CONSUMER_ID` | catalog | walmart.io consumer (application) UUID |
| `WM_KEY_VERSION` | catalog | private-key version (default `"1"`) |
| `WM_PRIVATE_KEY` | catalog | PEM-encoded PKCS#8 RSA private key for request signing |
| `WM_PUBLISHER_ID` | catalog | Impact Radius publisher id (optional, for attribution) |
| `CARTRIGHT_ORDER_HISTORY_PATH` | order history | path to the structured order-history JSON |

Construct the real adapters via `WalmartCatalogPricingAdapter.from_env()` and
`JsonFileOrderHistoryAdapter.from_env()`.

## Deliberately excluded from this repo

This is a public repository. A couple of things the running product depends on
are **intentionally not here**, and that is by design — don't go looking for them
or try to recreate them as part of the product surface:

- **The order-history self-scrape utility.** The order history is produced by a
  private, one-time self-scrape the user runs against their *own* Walmart
  account to export their *own* purchase history. That utility, and any
  personal-data seed scripts, live outside this repo. `JsonFileOrderHistoryAdapter`
  only ever consumes the **already-structured JSON output** it produces — it has
  no knowledge of how that file was made. Expected shape:

  ```json
  [{"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-01"}]
  ```

- **Vendor API docs (`io-docs/`)** and personal artifacts (architecture decks,
  the local `.env`, the SQLite database) are gitignored. The walmart.io adapter
  is written against the *publicly documented* Affiliate API only.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
```

Tests use fixture/fake adapters exclusively — **no test hits a live walmart.io
endpoint or needs real credentials.** The catalog adapter's HTTP client is
injectable, so its tests serve canned responses via `httpx.MockTransport`.
