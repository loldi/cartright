"""Production entrypoint: wire the real components into a live, deployable system.

Everywhere else in this project the adapter boundary is filled with fakes (per
the PRD's Testing Decisions). This module is the one place that assembles the
*real* adapters - live Claude completions, real Telegram messaging, real
walmart.io pricing, real scraped order history, a file-backed SQLite store - into
a running service. It is deliberately thin wiring with no decision logic of its own, so it
carries no unit tests (`# pragma: no cover`); every behavioral piece it composes
is tested in isolation against fakes.

Run the web service (SMS webhook + review page) with uvicorn's factory mode:

    uvicorn cartright.main:build_app --factory --host 0.0.0.0 --port $PORT

Set CARTRIGHT_RUN_SCHEDULER=1 to also start the proactive alert loop in a
background thread inside the same process (simplest single-service deploy).
"""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI

from cartright.interaction.web import create_app
from cartright.llm.claude import ClaudeAlertComposer, ClaudePreferenceParser
from cartright.ratelimit import RateLimiter
from cartright.scheduler import run_forever
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.order_history import JsonFileOrderHistoryAdapter
from cartright.shopping_engine.adapters.telegram import TelegramMessenger
from cartright.shopping_engine.adapters.walmart import WalmartCatalogPricingAdapter


def build_engine() -> ShoppingEngine:  # pragma: no cover - production wiring
    """Assemble the engine on real adapters and a file-backed SQLite store."""
    return ShoppingEngine(
        order_history=_load_order_history(),
        catalog=WalmartCatalogPricingAdapter.from_env(),
        db_path=os.environ.get("CARTRIGHT_DB_PATH", "cartright.db"),
    )


def _load_order_history() -> JsonFileOrderHistoryAdapter:  # pragma: no cover
    """Boot with empty order history if the scrape file isn't on disk yet.

    The file lives on the persistent disk and is uploaded out-of-band (scp)
    after the first deploy - a missing file at boot is an expected transient
    state, not a reason to take the Telegram webhook and health check down
    with it. `readiness()` already reports this gap via `order_history_present`.
    """
    try:
        return JsonFileOrderHistoryAdapter.from_env()
    except FileNotFoundError:
        return JsonFileOrderHistoryAdapter(orders=[])


def _start_scheduler(
    engine: ShoppingEngine, messenger: TelegramMessenger
) -> None:  # pragma: no cover
    """Run the proactive alert loop in a daemon thread alongside the web app."""
    interval = int(os.environ.get("CARTRIGHT_SCHEDULER_INTERVAL_SECONDS", "3600"))
    thread = threading.Thread(
        target=run_forever,
        kwargs={
            "engine": engine,
            "composer": ClaudeAlertComposer(),
            "messenger": messenger,
            "user_chat_id": os.environ["CARTRIGHT_USER_CHAT_ID"],
            "interval_seconds": interval,
        },
        daemon=True,
        name="cartright-scheduler",
    )
    thread.start()


def build_app() -> FastAPI:  # pragma: no cover - production wiring
    """Build the production FastAPI app wired to real adapters.

    Used as a uvicorn factory (`--factory`), so nothing is constructed at import
    time and credentials are only required when the service actually boots.
    """
    engine = build_engine()
    messenger = TelegramMessenger.from_env()
    user_chat_id = os.environ["CARTRIGHT_USER_CHAT_ID"]

    app = create_app(
        parser=ClaudePreferenceParser(),
        engine=engine,
        messenger=messenger,
        user_chat_id=user_chat_id,
        webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET"),
        # Fail-closed by default; only an explicit "0" disables the secret check.
        validate_webhook=os.environ.get("CARTRIGHT_VALIDATE_TELEGRAM_SECRET", "1") != "0",
        # When set, /review requires a valid signed token (and alert links carry one).
        review_token_secret=os.environ.get("CARTRIGHT_REVIEW_TOKEN_SECRET"),
        # Caps /telegram throughput so a leaked webhook secret can't replay the
        # real chat_id to flood live Claude calls. Defaults live in interaction/web.py.
        rate_limiter=RateLimiter(
            max_requests=int(os.environ.get("CARTRIGHT_TELEGRAM_RATE_LIMIT", "20")),
            window_seconds=float(os.environ.get("CARTRIGHT_TELEGRAM_RATE_WINDOW_SECONDS", "60")),
        ),
    )

    if os.environ.get("CARTRIGHT_RUN_SCHEDULER") == "1":
        _start_scheduler(engine, messenger)

    return app
