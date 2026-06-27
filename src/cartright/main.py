"""Production entrypoint: wire the real components into a live, deployable system.

Everywhere else in this project the adapter boundary is filled with fakes (per
the PRD's Testing Decisions). This module is the one place that assembles the
*real* adapters - live Claude completions, real Twilio SMS, real walmart.io
pricing, real scraped order history, a file-backed SQLite store - into a running
service. It is deliberately thin wiring with no decision logic of its own, so it
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
from cartright.scheduler import run_forever
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.order_history import JsonFileOrderHistoryAdapter
from cartright.shopping_engine.adapters.twilio_sms import TwilioSmsAdapter
from cartright.shopping_engine.adapters.walmart import WalmartCatalogPricingAdapter


def build_engine() -> ShoppingEngine:  # pragma: no cover - production wiring
    """Assemble the engine on real adapters and a file-backed SQLite store."""
    return ShoppingEngine(
        order_history=JsonFileOrderHistoryAdapter.from_env(),
        catalog=WalmartCatalogPricingAdapter.from_env(),
        db_path=os.environ.get("CARTRIGHT_DB_PATH", "cartright.db"),
    )


def _start_scheduler(engine: ShoppingEngine, twilio: TwilioSmsAdapter) -> None:  # pragma: no cover
    """Run the proactive alert loop in a daemon thread alongside the web app."""
    interval = int(os.environ.get("CARTRIGHT_SCHEDULER_INTERVAL_SECONDS", "3600"))
    thread = threading.Thread(
        target=run_forever,
        kwargs={
            "engine": engine,
            "composer": ClaudeAlertComposer(),
            "twilio": twilio,
            "user_number": os.environ["CARTRIGHT_USER_NUMBER"],
            "review_base_url": os.environ["CARTRIGHT_REVIEW_BASE_URL"],
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
    twilio = TwilioSmsAdapter.from_env()
    user_number = os.environ["CARTRIGHT_USER_NUMBER"]

    app = create_app(
        parser=ClaudePreferenceParser(),
        engine=engine,
        twilio=twilio,
        user_number=user_number,
        twilio_auth_token=os.environ["TWILIO_AUTH_TOKEN"],
        # Fail-closed by default; only an explicit "0" disables signature checks.
        validate_twilio_signature=os.environ.get("CARTRIGHT_VALIDATE_TWILIO_SIGNATURE", "1") != "0",
    )

    if os.environ.get("CARTRIGHT_RUN_SCHEDULER") == "1":
        _start_scheduler(engine, twilio)

    return app
