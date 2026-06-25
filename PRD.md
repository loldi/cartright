# Cartright — PRD

## Problem Statement

Current "AI Commerce" assistants (Walmart Sparky, Amazon Rufus, and similar) behave like search engines with a chat skin: I ask, they answer, I still do all the work of remembering what I need, when I need it again, and whether a given deal is actually relevant to me. None of them know my behavior over time, none of them reach out to me unprompted, and none of them are trusted to carry a purchase decision past "search results" — even when I'd be willing to grant that trust.

As a shopper, I want something that behaves like an actual personal assistant: it should know what I habitually buy and roughly when I'll need it again without me re-stating it every time, it should come to me when something's worth telling me rather than waiting for me to open an app, and it should get a purchase all the way to "ready to buy" so my only remaining job is to approve it. I want to interact with it the way I already interact with people I trust to help me — by texting — not through a retailer's app.

## Solution

A texting-based personal shopping agent ("Cartright") that:

- Learns real purchase history and infers consumption cadence for recurring/consumable items (e.g. paper towels), so it can predict a reorder window without being told.
- Lets the user state explicit preferences once (brand, size, etc.) and have them stick, overriding anything inferred.
- Never substitutes an item on its own initiative: a substitute product can only reach the cart if the shopper has explicitly granted substitution for that item/category. No grant means no substitution, full stop — this is the default posture, not an opt-out.
- Only checks for deals on a tracked item during its predicted reorder window, not continuously — the absence of noise is itself the personalization.
- Reaches out proactively via SMS when, and only when, something is worth surfacing.
- Builds a complete, real cart and shows it in a comprehensive review screen before anything is purchased; a real purchase only ever happens after an explicit human tap, never silently.
- Is scoped to Walmart only, and built exclusively against publicly documented Walmart APIs — no non-public systems or knowledge are used anywhere in the implementation.

This system is also the empirical basis for a companion written thesis and demo recording arguing that current AI Commerce is glorified search, and documenting precisely which public-API gaps (no consumer order-history read API, no consumer checkout API) currently block anyone from doing better.

## User Stories

1. As a shopper, I want the agent to know what I've bought in the past, so that it doesn't need me to manually enter my shopping habits.
2. As a shopper, I want the agent to infer how often I reorder a given consumable from my real purchase history, so that it can predict when I'll need it again without me telling it.
3. As a shopper, I want the agent to only start checking for deals on an item as my predicted reorder window approaches, so that I'm not bothered with irrelevant offers right after I've just bought something.
4. As a shopper, I want to be able to tell the agent an explicit preference (e.g. "always get the Bounty"), so that it stops guessing once I've told it directly.
5. As a shopper, I want my explicitly stated preferences to always override anything the agent inferred on its own, so that I stay in control of my own shopping identity.
6. As a shopper, I want substitutions to never happen unless I've explicitly told the agent it's allowed to substitute for a given item/category, so that I never end up with a product I didn't ask for just because something was out of stock or cheaper elsewhere.
7. As a shopper, I want to be able to correct a preference (including a substitution grant) at any time via text, so that the agent adapts as my needs change.
8. As a shopper, I want the agent to text me unprompted when it finds a relevant deal on something I'm about to need again, so that I don't have to remember to check myself.
9. As a shopper, I want the agent to never text me about deals on items I'm not close to needing, so that the relationship doesn't degrade into spam.
10. As a shopper, I want to be able to text the agent casually (not through a rigid menu/command syntax), so that the interaction feels like messaging a person, not operating a bot.
11. As a shopper, when the agent finds a deal or otherwise proposes a purchase, I want to see a real, itemized review of the full cart (items, prices, substitutions, total) before anything happens, so that I always know exactly what I'd be buying.
12. As a shopper, I want the review to be a real webpage I can open from the text, not just a wall of SMS text, so that I can actually evaluate a multi-item cart comfortably.
13. As a shopper, I want a single clear action from the review screen that hands me off to my real Walmart cart, so that I complete the actual purchase myself with full control.
14. As a shopper, I want the agent to never complete a purchase on its own, so that I never wake up to a charge I didn't explicitly approve.
15. As a shopper, I want the agent to track more than one recurring item at a time, so that it's a genuinely useful ongoing assistant rather than a single-purpose paper-towel reminder.
16. As a shopper, I want the agent's reasoning to be grounded in real prices and real availability, so that it never tells me about a "deal" that isn't actually real.
17. As a shopper, I want the agent to keep working over time (not just for a single session), so that it can genuinely catch a real reorder window whenever it actually arrives.
18. As a shopper, I want my conversation history and preferences to persist across days/weeks, so that I don't have to re-teach the agent every time I text it.
19. As a builder validating this thesis, I want the underlying decision logic (cadence inference, deal evaluation, preference resolution) to be deterministic and independently verifiable, so that I can demonstrate it's real reasoning and not an LLM hallucinating plausible-sounding numbers.
20. As a builder validating this thesis, I want to be able to show the system being driven by a live LLM during a recorded demo, so that the demo is honest evidence for the written argument rather than a staged mockup.
21. As a builder publishing this work, I want the public repository to contain everything needed to understand and run the core agent, while excluding the specific utility that scraped my personal Walmart account, so that the published project doesn't ship a public scraper as its headline artifact.

## Implementation Decisions

**Module shape (4 modules + adapters + a scheduler):**

- **LLM layer** — owns the system prompt and conversational orchestration. Framed as "commerce-forward": proactive, decisive, concise, and required to ground every claim about price/availability/cadence in real `ShoppingEngine` output — never permitted to assert a price, deal, or reorder timing it invented itself.
- **ShoppingEngine** — the single seam for this project, placed *below* the LLM layer (not at the LLM's tool-call boundary), specifically so tests don't depend on non-deterministic LLM tool-call behavior. Exposes a small deterministic interface: `getReorderCandidates()`, `evaluateDeal()`, `buildCart()`, `recordPreference()` (plus a read accessor for current preferences). Owns its own persistence (SQLite) internally — not part of the exposed interface.
- **Interaction module (Twilio)** — inbound/outbound SMS only, single private number, single user. Not multi-tenant.
- **Review-order UI (web)** — a separate surface from the Twilio module: a small server-rendered page (FastAPI + HTMX + Tailwind, matching existing stack defaults) that renders a `buildCart()` result as an itemized review with a single CTA that hands off to a real Walmart cart/checkout link. Never submits a purchase itself.
- **Adapters (not top-level modules, sit behind the `ShoppingEngine` seam):** an order-history reader (consumes the output of a private, excluded self-scrape utility — see Out of Scope/Further Notes), a Walmart catalog/pricing client (built against publicly documented walmart.io APIs only), and the Twilio client. Production wires real adapters; tests wire fixture adapters satisfying the same interface.
- **Scheduler** — thin, not a deep module. Periodically calls `getReorderCandidates()` and, if a deal is found within a candidate's reorder window, hands off to the LLM layer to compose and send the SMS alert.

**Data and reasoning:**

- Order history is sourced once, interactively, via a self-scrape of the user's own logged-in Walmart.com session (private utility, excluded from the public repo). The public `ShoppingEngine` only ever consumes the resulting structured order-history data through its adapter interface — it has no knowledge of how that data was produced.
- Cadence is inferred from the interval between past orders of the same/equivalent item, producing a predicted reorder window (a date range, not a single date) per tracked item.
- Deal evaluation only runs for a tracked item while it's inside its predicted reorder window — this windowing is the core personalization mechanism, not a nice-to-have.
- Preferences are stored as a structured profile per item/category (preferred attributes + a source flag: `inferred` or `explicit`). Explicit preferences always take precedence over inferred ones.
- Substitution is default-deny, not default-allow-with-opt-out: `buildCart()` may only place a substitute product on a cart line if the shopper has an explicit, recorded substitution grant for that item/category. No preference on file means no substitution — the absence of a "never substitute" flag is not implicit permission to substitute. This is stronger than a plain opt-out and must be enforced in `ShoppingEngine`/`build_cart`, not left to whatever the catalog adapter happens to return.
- The engine is built generically against whatever categories exist in the real order history — not hardcoded to a single item — even though the recorded demo only walks one item through the full pipeline end-to-end.

**Purchasing model:**

- Approve-then-handoff only. `buildCart()` produces cart data for review; nothing in this system ever submits a real order. The review-order UI's CTA opens a real Walmart cart/checkout link for the user to complete manually. No auto-submit code path exists anywhere in this project.

**Scope and provenance:**

- Walmart only for this iteration; Amazon explicitly deferred.
- Built exclusively against publicly documented Walmart APIs (walmart.io developer docs, to be supplied during implementation). No non-public Walmart systems, endpoints, or internal knowledge are used anywhere in code, prompts, or comments.

**LLM:** Claude (Sonnet) via the Claude API, default choice unless cost or behavior in practice says otherwise.

**Hosting/persistence:** A minimal always-on deployment on a free or low-cost cloud host (Render/Fly.io-class), willing to absorb marginal cost if load requires it. SQLite is sufficient at this scale and is owned entirely inside `ShoppingEngine`.

**Demo recording:** Driven by live LLM completions and real `ShoppingEngine` logic against the user's real (privately held) scraped data. Only the *timing* of when a cadence/deal-check fires is staged for the recording — response content is never pre-written.

**Repo:** Public, standalone repo named **Cartright**. Ships the LLM layer, `ShoppingEngine` (including a fixture adapter for the order-history seam), the Interaction module, the Review-order UI, and the scheduler. Excludes the private self-scrape utility and any other one-off setup/seed scripts used to populate real personal data.

## Testing Decisions

- A good test in this project exercises `ShoppingEngine`'s public interface (`getReorderCandidates`, `evaluateDeal`, `buildCart`, `recordPreference`) with plain fixture data in, plain data out — no real network calls (Walmart API, Twilio) and no real LLM completions in the test path. This is where the bulk of test coverage should concentrate, since it's the deterministic, decision-bearing logic (cadence math, deal evaluation, preference precedence) that the thesis's credibility actually rests on.
- The LLM layer is not tested with strict equality/tool-call assertions, since LLM behavior is inherently non-deterministic and such tests would be brittle by construction. Verify it instead via scripted conversation transcripts reviewed qualitatively, plus a light integration smoke-test confirming it calls the expected `ShoppingEngine` methods for a given scripted scenario.
- The catalog/pricing adapter and the Twilio adapter are tested via fakes that satisfy the same interface `ShoppingEngine` depends on. No test should hit a real Walmart endpoint or send a real SMS.
- The Review-order UI is tested as a thin rendering layer: given fixture cart data (a `buildCart()`-shaped object), assert on rendered output — never against live data.
- This is a greenfield project; there is no prior in-repo test convention to follow. This PRD establishes the convention going forward.

## Out of Scope

- Amazon integration of any kind (explicitly deferred to a possible future iteration).
- Fully automated checkout/auto-submit purchasing. This iteration never completes a real purchase without an explicit manual tap from the user.
- Multi-user or multi-tenant support. Single user, single private phone number.
- Persistent or background account scraping. The Walmart order-history scrape is a one-time, interactive, self-initiated action against the user's own account — not a running service.
- WhatsApp or any channel other than SMS.
- Any non-public Walmart API, system, or internal knowledge.
- Production-grade uptime/SLA guarantees. Minimal/free-tier hosting is acceptable; occasional downtime is tolerated.

## Further Notes

- This system is the empirical basis for a companion written thesis (structure: a sharp opening claim, the build as supporting evidence, then an honest section enumerating the specific public-API gaps hit during implementation — no consumer order-history read API, no consumer checkout API) and a short demo video, both intended for public/LinkedIn distribution.
- The self-scrape utility, and any other scripts used purely to set up or seed the demo with the user's real personal data, are deliberately excluded from the public repo — they are demo-production tooling, not part of the product surface being argued for.
- No issue tracker currently exists for this project; this PRD has not yet been published anywhere pending that decision (GitHub Issues is the likely default once the repo is initialized).
