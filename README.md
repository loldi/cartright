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

### walmart.io credential setup (one-time)

The catalog adapter authenticates every call with an RSA-signed request, so you
need a walmart.io Affiliate application and a signing keypair before the
`WM_*` vars above mean anything. Per the documented setup flow:

1. **Create a Walmart.com account**, then sign in to the
   [Walmart I/O developer portal](https://walmart.io/) and **create an
   application** for the Affiliate (Product) API.
2. **Generate an RSA keypair** locally (2048-bit), as PKCS#8:

   ```bash
   openssl genrsa -out wm_private.pem 2048
   openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt \
     -in wm_private.pem -out wm_private_pkcs8.pem
   openssl rsa -in wm_private.pem -pubout -out wm_public.pem
   ```

3. **Upload the public key** (`wm_public.pem`) in the portal. Your
   `WM_CONSUMER_ID` is issued *after* this, and the key gets a version number
   (usually `1`) — that's your `WM_KEY_VERSION`.
4. **Set the secrets:** `WM_CONSUMER_ID` from the portal, `WM_KEY_VERSION` for
   the uploaded key, and `WM_PRIVATE_KEY` = the contents of
   `wm_private_pkcs8.pem`. `WM_PRIVATE_KEY` accepts either the PEM block (keep
   the newlines) or the raw base64 DER the docs describe. `WM_PUBLISHER_ID`
   (Impact Radius id) is optional, only used for commission attribution.

The signature has a **180-second TTL**, so the host clock must be roughly
accurate; a stale timestamp returns a "timestamp expired" error. (`zipCode` /
`storeId` request scoping is optional and not wired — pricing defaults to the
documented San Bruno location, and `storeId` requires Walmart business-team
approval.)

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

1. **Preflight:** with your `.env` filled in, run `cartright doctor` (or
   `python -m cartright doctor`). It validates every required var (presence,
   key parses, phone numbers are E.164, order-history file exists, review URL is
   https) without any network call and without printing a secret. Fix anything
   it flags before deploying.
2. **Verify each live seam** (one real call each, run locally with your `.env`):
   - `cartright catalog-check <itemId>` — confirms your walmart.io credentials +
     request signing work; prints a real price.
   - `cartright orders-check` — validates your real order-history file and prints
     the reorder candidates inferred from it.
   - `cartright sms-check <your-number>` — sends one real test SMS; confirm it
     arrives.
3. Deploy the service and set all secrets from the table above.
4. In the Twilio console, point the SMS number's **inbound webhook** at
   `https://<your-host>/sms` (HTTP POST).
5. Set `CARTRIGHT_REVIEW_BASE_URL` to `https://<your-host>/review`.
6. Verify end-to-end: text a preference to the Twilio number and confirm a
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
