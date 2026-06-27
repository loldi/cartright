# Cartright

A messaging-based personal shopping agent for Walmart. Cartright learns what you
reorder and when, watches for real deals inside each item's predicted reorder
window, and messages you (over Telegram) only when something is genuinely worth
your time. Every
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
  - `Messenger` — outbound chat messages. Production impl (`TelegramMessenger`)
    uses the Telegram Bot API; inbound arrives via the `/telegram` webhook.
- **`llm/`** — Claude-backed preference parsing and deal-alert composition.
- **`interaction/`**, **`review/`**, **`scheduler.py`** — the Telegram webhook,
  the itemized review UI, and the proactive alert loop.

## Configuration (production)

All real adapters and the production entrypoint read config from the
environment. Copy [`.env.example`](.env.example) to `.env` and fill it in (or
set these as host secrets):

| Variable | Used by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | LLM | Claude API key (preference parsing + alert composition) |
| `TELEGRAM_BOT_TOKEN` | messaging | Telegram bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | messaging | secret token passed to `setWebhook`; verified on inbound `/telegram` |
| `WM_CONSUMER_ID` | catalog | walmart.io consumer (application) UUID |
| `WM_KEY_VERSION` | catalog | private-key version (default `"1"`) |
| `WM_PRIVATE_KEY` | catalog | PEM-encoded PKCS#8 RSA private key for request signing |
| `WM_PUBLISHER_ID` | catalog | Impact Radius publisher id (optional, for attribution) |
| `CARTRIGHT_USER_CHAT_ID` | app | the single private Telegram chat id this instance serves |
| `CARTRIGHT_ORDER_HISTORY_PATH` | order history | path to the structured order-history JSON |
| `CARTRIGHT_DB_PATH` | engine | file-backed SQLite path (default `cartright.db`) |
| `CARTRIGHT_REVIEW_BASE_URL` | scheduler | public base URL of `/review`, used in alert links |
| `CARTRIGHT_VALIDATE_TELEGRAM_SECRET` | app | validate `X-Telegram-Bot-Api-Secret-Token` on `/telegram`; default on, set `0` to disable |
| `CARTRIGHT_REVIEW_TOKEN_SECRET` | app | HMAC secret for signed review links; when set, `/review` requires a valid token. Use the same value locally and on the host |
| `CARTRIGHT_RUN_SCHEDULER` | app | `1` to run the alert loop in-process |
| `CARTRIGHT_SCHEDULER_INTERVAL_SECONDS` | scheduler | alert-loop interval (default `3600`) |

The real adapters expose `from_env()` constructors
(`WalmartCatalogPricingAdapter`, `JsonFileOrderHistoryAdapter`,
`TelegramMessenger`); the production entrypoint `cartright.main` wires them all
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

### Telegram bot setup (one-time)

Cartright talks to you through a Telegram bot — no carrier registration, no
per-message cost. To wire it up:

1. **Create a bot:** message [@BotFather](https://t.me/BotFather), send
   `/newbot`, and follow the prompts. It hands you a token like
   `123456789:AA...` — that's `TELEGRAM_BOT_TOKEN`.
2. **Find your chat id:** open a chat with your new bot and send it any message,
   then read the numeric `chat.id` from
   `https://api.telegram.org/bot<token>/getUpdates` (or message
   [@userinfobot](https://t.me/userinfobot)). That's `CARTRIGHT_USER_CHAT_ID` —
   the one chat this instance serves; updates from any other chat are ignored.
3. **Pick a webhook secret:** `openssl rand -hex 32` → `TELEGRAM_WEBHOOK_SECRET`.
   You pass the same value to `setWebhook` at deploy time (see "Going live"), and
   `/telegram` verifies it on every inbound update.

## Deployment

`cartright.main:build_app` is a uvicorn factory, so nothing is constructed at
import and credentials are only needed when the service actually boots:

```bash
uv run uvicorn cartright.main:build_app --factory --host 0.0.0.0 --port $PORT
```

With `CARTRIGHT_RUN_SCHEDULER=1`, the same process also runs the proactive alert
loop in a background thread, so a single always-on instance serves the
`/telegram` webhook, the `/review` page, and the scheduler.

A [`render.yaml`](render.yaml) Blueprint is included for one-click deploy on
Render (all secrets declared `sync: false`, set in the dashboard). Fly.io or any
container host works the same way.

### Going live (manual, one-time)

See [`GO-LIVE.md`](GO-LIVE.md) for the full ordered runbook. In short:

1. **Preflight:** with your `.env` filled in, run `cartright doctor` (or
   `python -m cartright doctor`). It validates every required var (presence,
   key parses, bot token and chat id are well-formed, order-history file exists,
   review URL is https) without any network call and without printing a secret.
   Fix anything it flags before deploying.
2. **Verify each live seam** (one real call each, run locally with your `.env`):
   - `cartright catalog-check <itemId>` — confirms your walmart.io credentials +
     request signing work; prints a real price.
   - `cartright orders-check` — validates your real order-history file and prints
     the reorder candidates inferred from it.
   - `cartright message-check` — sends one real test message to your
     `CARTRIGHT_USER_CHAT_ID`; confirm it arrives in the Telegram chat.
3. Deploy the service and set all secrets from the table above. Then confirm
   `https://<your-host>/health` returns `200` with every `*_configured` field
   `true` (it's a secret-free readiness report, booleans only), and that
   `https://<your-host>/review?item=<id>` renders for a known item.
4. **Register the Telegram webhook** so updates reach your service (one HTTPS
   call, with the same secret you put in `TELEGRAM_WEBHOOK_SECRET`):

   ```bash
   curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
     -d "url=https://<your-host>/telegram" \
     -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
   ```

   The endpoint validates the `X-Telegram-Bot-Api-Secret-Token` on every request
   (fail-closed), so a spoofed POST is rejected with `403`; this is on by default
   (`CARTRIGHT_VALIDATE_TELEGRAM_SECRET`).
5. Set `CARTRIGHT_REVIEW_BASE_URL` to `https://<your-host>/review`.
6. Verify end-to-end: message a preference to your bot and confirm a live-Claude
   confirmation comes back; and run `cartright alert-once` to fire one proactive
   alert on demand (instead of waiting for the hourly tick) and confirm it
   arrives with a working review link.

### Secure operations

This service holds four sets of real credentials (Anthropic, Telegram,
walmart.io, plus your personal order history). Once it's live:

- **Enable 2FA** on Render, Telegram, Anthropic, and the Walmart developer
  portal, and restrict who can view the host dashboard / environment. Whoever can
  read the host's env or shell into the instance has every credential.
- **Rotate keys** if dashboard access ever changes hands.
- **Treat the persistent disk as sensitive.** The order-history JSON is personal
  PII (your purchase history) and the SQLite DB holds your preferences. Don't
  sync either anywhere public.
- **Never enable `httpx` / `urllib3` DEBUG logging or rich-traceback-with-locals
  in production.** Normal tracebacks don't include local values, so the walmart
  request signature and the Telegram bot token (which rides in the request URL)
  stay out of your logs; those tools would change that. The app itself does no
  logging and returns generic `500`s (no stack traces to clients).
- **The `/review` endpoint is rate-limited and item-capped, and (when
  `CARTRIGHT_REVIEW_TOKEN_SECRET` is set) requires a signed, non-expired link
  token** — so a stranger who finds the URL can't drive walmart.io calls. Set
  the secret in production.
- **Keep dependencies pinned** (`uv.lock` with hashes); update deliberately.

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
endpoint, sends a real message, or makes a real Claude call, and none need real
credentials.** The catalog adapter's and the Telegram messenger's HTTP clients
are both injectable, so their tests serve canned responses
(`httpx.MockTransport`). The production entrypoint (`cartright.main`) is thin
wiring with no logic of its own and is intentionally untested.
