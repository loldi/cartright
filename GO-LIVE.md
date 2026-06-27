# Cartright — Go-Live Runbook

An ordered checklist to take Cartright from a code-complete repo to a live,
demoable deployment. Each step is verifiable; the `cartright` CLI commands do
one real check each. See [`README.md`](README.md) for the env-var table,
walmart.io credential setup, and the "Secure operations" notes.

> The product and its go-live tooling are built and unit-tested against fakes.
> Everything below is the **operator** work: real credentials, a real host, and
> one real run of each check.

## 0. Prerequisites (accounts)

- [ ] Walmart I/O (Affiliate API) application + uploaded public key
      (see README → "walmart.io credential setup").
- [ ] Telegram bot via @BotFather (token + your chat id; no carrier
      registration, no per-message cost). See README → "Telegram bot setup".
- [ ] Anthropic API key.
- [ ] A host account (Render, via the included [`render.yaml`](render.yaml), or
      any container host).
- [ ] Your order-history JSON, produced by your private self-scrape, at the path
      you'll set as `CARTRIGHT_ORDER_HISTORY_PATH`.

## 1. Configure

- [ ] Copy [`.env.example`](.env.example) to `.env` and fill in every value.
- [ ] Generate `CARTRIGHT_REVIEW_TOKEN_SECRET` (`openssl rand -hex 32`) and set
      the **same** value in `.env` and on the host — it signs review links and is
      verified by `/review`, so a mismatch makes alert links 403.
- [ ] Generate `TELEGRAM_WEBHOOK_SECRET` (`openssl rand -hex 32`) and set the
      **same** value in `.env`, on the host, and as the `secret_token` you pass
      to `setWebhook` (§5) — `/telegram` rejects updates without it.

## 2. Preflight (no network)

- [ ] `cartright doctor` — validates presence + format of every required var
      (key parses, bot token + chat id are well-formed, order file exists,
      review URL is https). Fix anything it flags. It never prints a secret.

## 3. Verify each live seam (one real call each)

- [ ] `cartright catalog-check <itemId>` — a real walmart.io price comes back
      (proves credentials + request signing).
- [ ] `cartright orders-check` — your real order file is well-formed and yields
      sensible reorder candidates.
- [ ] `cartright message-check` — you receive a test message in your Telegram
      chat (sends to `CARTRIGHT_USER_CHAT_ID`).

## 4. Deploy

- [ ] Deploy via the Render Blueprint (`render.yaml`); set every secret in the
      dashboard (they're declared `sync: false`, never committed).
- [ ] Confirm `https://<host>/health` returns `200` with every `*_configured`
      field `true` (secret-free readiness report).
- [ ] Confirm `https://<host>/review?item=<id>` renders for a known item.

## 5. Connect Telegram

- [ ] Register the webhook so updates reach the host (same value as
      `TELEGRAM_WEBHOOK_SECRET`):

      ```bash
      curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
        -d "url=https://<host>/telegram" \
        -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
      ```

      `/telegram` validates `X-Telegram-Bot-Api-Secret-Token` (fail-closed), so
      spoofed POSTs get `403`.
- [ ] Set `CARTRIGHT_REVIEW_BASE_URL` to `https://<host>/review`.

## 6. Verify end-to-end (live Claude)

- [ ] **Inbound:** message a casual preference to your bot; confirm a live-Claude
      confirmation comes back and the preference persists.
- [ ] **Proactive:** run `cartright alert-once` (triggers one alert cycle now
      instead of waiting for the hourly tick). Confirm a real alert SMS arrives
      with a working `/review` link; open it, confirm the itemized cart + the
      Walmart hand-off link, and confirm a substitute is **not** present unless
      you've granted substitution for that item (default-deny).

## 7. Record the demo

- [ ] Run the full pass (inbound preference → in-window deal → alert → review →
      hand-off), driven by live Claude and your real data. Only the *timing* of
      the alert is staged (`alert-once`); all content is live.

## After go-live

Review the "Secure operations" section in [`README.md`](README.md): 2FA on every
console, restrict dashboard access, rotate keys if access changes, treat the
order-history/SQLite disk as PII, and never enable `httpx`/`urllib3` DEBUG
logging in production.
