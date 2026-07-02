# Cartright — Build Retrospective

*Executive summary of the project from idea to live, written for a product audience.*

---

## What we were trying to prove

The pitch for Cartright was a simple provocation: every "AI shopping assistant" on the market right now is just a search bar with better copywriting. You ask it something, it tells you things, you still do all the work. There's no memory, no proactive behavior, no trust. Nothing that behaves like an actual assistant.

Cartright was built to show what a real personal shopping agent looks like — one that knows your purchase history, infers when you're about to need something again, watches for a genuinely good deal inside that window, and texts you unprompted when one shows up. You don't open an app. You don't ask it anything. It comes to you when there's something worth saying.

That's the product argument. But it was also a research argument: the companion thesis is specifically about *why no one has shipped this before*, and the honest answer is that the public APIs needed to do it properly don't fully exist yet. There's no public consumer order history API. There's no public checkout API. Building the agent exposes both gaps in a concrete, demonstrable way, which is more interesting than just asserting them.

---

## How it was built

**The approach: vertical slices, test-first, no hand-waving.**

The build ran as a sequence of small end-to-end slices, each one producing something real and verifiable before the next started. The rule from the beginning was that the decision logic — cadence math, deal evaluation, preference precedence — had to be deterministic and independently auditable. The LLM sits on top and handles language; it doesn't touch the numbers. That separation is itself the thesis point: AI commerce doesn't need to hallucinate deal math if the plumbing is honest.

**The slices, roughly:**

1. **Scaffold** — project structure, CI, the `ShoppingEngine` skeleton with its adapter interfaces defined. No real behavior yet, just the shape.
2. **Cadence inference** — given a purchase history, infer when someone will need something again. The math is simple on purpose: average the gaps between orders, add a margin based on how irregular those gaps were. A steady consumable gets a tight window; an erratic one gets a wide one. No black box.
3. **Deal evaluation + review UI** — plug in real prices, decide what "a deal" means (in-stock, reference price exists, current price is at least 10% lower), and render an itemized review page the user can evaluate before doing anything.
4. **Proactive alert loop** — the scheduler: check candidates, only evaluate deals for items inside their reorder window, compose an alert via Claude when something's worth surfacing, send it.
5. **Preference capture** — a conversational interface for stating preferences over Telegram. "Always get the Bounty" gets stored as an explicit preference that overrides anything inferred.
6. **Real adapters** — wire up the actual Walmart catalog API (publicly documented Affiliate API only, RSA-signed requests), the real order history file, and the real Telegram bot.
7. **Go-live hardening** — operator CLI (`cartright doctor`, `catalog-check`, `orders-check`, `message-check`, `alert-once`), security hardening on the webhook and review endpoints, Render deployment, dependency scanning.

---

## The surprises

**Twilio doesn't work for this.** The original plan was SMS via Twilio. Got the API working, credentials authenticated, outbound calls succeeding — and then every message came back `undelivered`. US carrier rules (A2P 10DLC, toll-free verification) now gate all programmatic SMS delivery, and the registration process is designed for businesses sending at scale, not a personal agent with one recipient. Switched to Telegram. The adapter abstraction made this a one-afternoon swap: engine, LLM, deal logic, cart, and the preference orchestration were all untouched. Only the transport seam moved.

Telegram turned out to be better for the use case anyway — no per-message cost, no carrier registration, richer message formatting, and it actually reads like getting a text from someone.

**The deploy deadlocked.** First Render deployment crash-looped. The app tried to load the order history file on startup, the file wasn't there yet (it lives on a persistent disk that has to be manually uploaded), so the whole service died before the socket bound. The problem: Render only lets you SSH into a *running, healthy* instance. The instance couldn't be healthy without the file. The file couldn't be uploaded without SSH. A genuine circular dependency. Fix was simple — boot healthy with empty orders, surface a "file missing" flag on `/health`, let the operator upload the file once the service is reachable. But it was a good reminder that "works locally" and "works on cold infrastructure" are different tests.

**The first real alert fired before we planned it.** The scheduler is designed to run immediately on boot before its first sleep interval. On the first successful deploy with real data loaded, Dove Body Wash was inside its inferred reorder window and had a live price drop. The system composed a message, sent it to Telegram, the review link rendered correctly, the cart handoff worked. Nobody triggered it manually. This was the first time the full pipeline ran end-to-end with real data — order history to cadence inference to live Walmart price check to Claude composition to Telegram delivery to Walmart cart — and it happened on its own, which is the point.

**Duplicate alerts showed up fast.** Two hours after the first alert, a second one for the same deal landed. The dedup logic hadn't been built yet — the scheduler just re-evaluated everything every hour and re-sent if the deal was still active. Fixed with a per-window dedup rule keyed on the exact reorder window, not a time-based cooldown. Then immediately refined: a strictly *lower* price within the same window should still alert, because that's genuinely new information. Two test-first slices to get the semantics right.

**The cadence logic has no concept of "consumable."** Once real order history was loaded, the decision log showed AirPods, a Seagate external hard drive, a D&D board game, and two scented candles as live "reorder candidates" — items bought twice that the cadence math correctly identified as having a pattern, but that no reasonable person would expect to replenish on a schedule. The cadence inference doesn't know the difference between "I buy this every 30 days" and "I bought this twice and it was coincidental." This is now the one open issue blocking a broader rollout, and it's the right kind of problem to have: the system is honest enough about its own reasoning that the gap is visible and inspectable.

---

## What worked well

**The adapter seam held up.** The design decision to put a clean interface between the `ShoppingEngine` and every external dependency (order history, catalog pricing, messaging) paid off multiple times. Real order history swapped in with no behavior change. Twilio to Telegram was a one-seam swap. The fixture adapters used in tests meant 152 tests run with no live API calls, no real credentials, and no Walmart price checks — which mattered when the same tests needed to run in CI on every push.

**The audit trail earned its keep fast.** The `cartright decisions` command (a log of why each item was sent or skipped each cycle) was built one day before it revealed the duplicate-alert bug and the durables-as-candidates issue. Both problems were diagnosed in minutes rather than hours because the reasoning was persisted and inspectable. "What did it do and why" is more useful than "what did it send."

**The security posture held up to scrutiny.** Every external input is authenticated before reaching any paid API. Webhook secrets, rate limits, item caps, signed review links — all built before the first public deployment. The threat model conversation that prompted the `/telegram` rate limit was a good forcing function: structural gates over prompt-level defenses. Unauthenticated input never reaches Claude.

---

## The honest gaps

The thesis the companion piece will argue: current AI commerce is glorified search because two specific public APIs don't exist.

1. **No consumer order history read API.** Walmart doesn't expose a consumer-authenticated endpoint to read your own purchase history. Everything Cartright infers about cadence comes from a private self-scrape of the Walmart order pages — which works, but it's a one-time manual step, not an ongoing integration. Any real commercial version of this agent would need this API.

2. **No consumer checkout API.** Cartright gets you to "cart is ready, here's the link" — the human taps once to open their real Walmart cart and completes the purchase. That's the right UX for a trust-building MVP. But the gap is real: there's no documented API path from "cart is ready" to "purchase is submitted." The approve-then-handoff model isn't just a safety choice; it's also the only option.

Both gaps are known. Both are intentional Cartright design decisions, documented explicitly. The thesis argues that acknowledging them honestly is more interesting than pretending they don't exist.

---

## Where things stand

The original PRD is fully delivered. The system is live, running, and has fired real alerts on real deals with real purchase history. All 152 tests pass. CI includes ruff, mypy, and dependency vulnerability scanning. The go-live epic is closed.

**One open issue before broader sharing:** the reasoning gate (#50). The current cadence logic needs an LLM-layer classifier that evaluates "is this actually a recurring consumable" before escalating to a deal check. The AirPods case is the tell. This is the right next piece before inviting anyone else to look at the decision log.

**Three post-MVP epics for later:**
- Pluggable messaging channels (multi-channel transport)  
- A public product page for Cartright  
- Whatever general-release looks like once the reasoning gate is in

The demo recording and thesis draft are the immediate next moves. The system can run them now.

---

*Cartright — built June 24–29, 2026. Total PRD slices: 9. Total go-live slices: 7. Final test count: 152. Days from scaffold to first live alert: 5.*

---

## Thesis notes *(raw — to be refined)*

**On the core promise of AI:**
Cartright's goal is to embody the kind of benefit AI was actually promised to deliver: a tool that makes life genuinely easier. The thesis frames Cartright as an intuitive interface through which users save time and get on with the things they'd rather be doing. Not a novelty, not a demo — a tool that quietly handles something real so the human doesn't have to think about it.

**On what Sparky and Rufus get wrong:**
Part of what I believe that existing native solutions, like Sparky or Rufus, get wrong is that they inherently rely on the user interacting with the native app. Sure, when I'm actively shopping it makes sense for me to be in the Walmart app and possibly engaging with Sparky. But what about the rest of the time? What about the random, unscheduled moments throughout the day where we are reminded "Hey we're out of paper towels" or "weren't you going to look at deck umbrellas?" Those transient moments where you *could* stop what you're doing and actually re-order the paper towels or check prices on deck furniture, but don't. Working with agentic shoppers shouldn't be a hassle. To me that defeats AI's entire purpose. Will behaviors need to change? Sure they will. But it should feel like a natural change that already fits in to the way people do things.

That's the gap Cartright aims to live in. A personal shopping agent that lives directly inside your messaging applications.

Pop open the thread, shoot off a message, and move on with your day. That's it.
