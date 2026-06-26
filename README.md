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

All real adapters and the production entrypoint read config from the
environment. Copy [`.env.example`](.env.example) to `.env` and fill it in (or
set these as host secrets):

| Variable | Used by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | LLM | Claude API key (preference parsing + alert composition) |
| `TWILIO_ACCOUNT_SID` | SMS | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | SMS | Twilio auth token |
| `TWILIO_FROM_NUMBER` | SMS | the Twilio number Cartright sends from (E.164) |
| `WM_CONSUMER_ID` | catalog | walmart.io consumer (application) UUID |
| `WM_KEY_VERSION` | catalog | private-key version (default `"1"`) |
| `WM_PRIVATE_KEY` | catalog | PEM-encoded PKCS#8 RSA private key for request signing |
| `WM_PUBLISHER_ID` | catalog | Impact Radius publisher id (optional, for attribution) |
| `CARTRIGHT_USER_NUMBER` | app | the single private number this instance serves (E.164) |
| `CARTRIGHT_ORDER_HISTORY_PATH` | order history | path to the structured order-history JSON |
| `CARTRIGHT_DB_PATH` | engine | file-backed SQLite path (default `cartright.db`) |
| `CARTRIGHT_REVIEW_BASE_URL` | scheduler | public base URL of `/review`, used in alert links |
| `CARTRIGHT_RUN_SCHEDULER` | app | `1` to run the alert loop in-process |
| `CARTRIGHT_SCHEDULER_INTERVAL_SECONDS` | scheduler | alert-loop interval (default `3600`) |

The real adapters expose `from_env()` constructors
(`WalmartCatalogPricingAdapter`, `JsonFileOrderHistoryAdapter`,
`TwilioSmsAdapter`); the production entrypoint `cartright.main` wires them all
together.

## Deployment

`cartright.main:build_app` is a uvicorn factory, so nothing is constructed at
import and credentials are only needed when the service actually boots:

```bash
uv run uvicorn cartright.main:build_app --factory --host 0.0.0.0 --port $PORT
```

With `CARTRIGHT_RUN_SCHEDULER=1`, the same process also runs the proactive alert
loop in a background thread, so a single always-on instance serves the `/sms`
webhook, the `/review` page, and the scheduler.

A [`render.yaml`](render.yaml) Blueprint is included for one-click deploy on
Render (all secrets declared `sync: false`, set in the dashboard). Fly.io or any
container host works the same way.

### Going live (manual, one-time)

1. Deploy the service and set all secrets from the table above.
2. In the Twilio console, point the SMS number's **inbound webhook** at
   `https://<your-host>/sms` (HTTP POST).
3. Set `CARTRIGHT_REVIEW_BASE_URL` to `https://<your-host>/review`.
4. Verify end-to-end: text a preference to the Twilio number and confirm a
   live-Claude confirmation SMS comes back, and/or let an in-window deal fire a
   proactive alert with a working review link.

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
endpoint, sends a real SMS, or makes a real Claude call, and none need real
credentials.** The catalog adapter's HTTP client and the Twilio adapter's client
are both injectable, so their tests serve canned responses (`httpx.MockTransport`
/ a fake Twilio client). The production entrypoint (`cartright.main`) is thin
wiring with no logic of its own and is intentionally untested.
