"""GL-5: the secret-free `/health` readiness report.

`readiness()` is a pure function over an env mapping, so most assertions pass a
dict directly. One integration test drives the real `/health` endpoint and
asserts no secret value appears in the response.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cartright.interaction.web import create_app
from cartright.llm.preferences import ParsedPreference
from cartright.preflight import readiness
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import (
    FixtureCatalogPricingAdapter,
    FixtureMessenger,
    FixtureOrderHistoryAdapter,
)

SECRET_API_KEY = "sk-ant-READINESSSECRET999"


def _pem_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def _full_env(orders_path: str) -> dict[str, str]:
    return {
        "ANTHROPIC_API_KEY": SECRET_API_KEY,
        "TELEGRAM_BOT_TOKEN": "123456789:AAFAKEtokenFAKEtokenFAKEtoken00",
        "WM_CONSUMER_ID": "11111111-2222-3333-4444-555555555555",
        "WM_PRIVATE_KEY": _pem_key(),
        "CARTRIGHT_USER_CHAT_ID": "987654321",
        "CARTRIGHT_ORDER_HISTORY_PATH": orders_path,
        "CARTRIGHT_REVIEW_BASE_URL": "https://x.example.com/review",
    }


def _orders_file(tmp_path: Path) -> str:
    path = tmp_path / "orders.json"
    path.write_text("[]", encoding="utf-8")
    return str(path)


def test_full_env_reports_every_subsystem_configured(tmp_path: Path) -> None:
    report = readiness(_full_env(_orders_file(tmp_path)))

    assert report == {
        "anthropic_configured": True,
        "telegram_configured": True,
        "walmart_configured": True,
        "order_history_present": True,
        "scheduler_enabled": False,  # CARTRIGHT_RUN_SCHEDULER unset
    }


def test_empty_env_reports_nothing_configured() -> None:
    report = readiness({})

    assert not any(report.values())


def test_scheduler_flag_reflects_env() -> None:
    assert readiness({"CARTRIGHT_RUN_SCHEDULER": "1"})["scheduler_enabled"] is True
    assert readiness({"CARTRIGHT_RUN_SCHEDULER": "0"})["scheduler_enabled"] is False


def test_malformed_key_makes_walmart_not_configured(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    env["WM_PRIVATE_KEY"] = "garbage"

    assert readiness(env)["walmart_configured"] is False


def test_missing_telegram_token_is_not_configured(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    del env["TELEGRAM_BOT_TOKEN"]

    assert readiness(env)["telegram_configured"] is False


def test_missing_order_file_is_not_present(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    env["CARTRIGHT_ORDER_HISTORY_PATH"] = str(tmp_path / "nope.json")

    assert readiness(env)["order_history_present"] is False


def _make_app() -> TestClient:
    engine = ShoppingEngine(
        order_history=FixtureOrderHistoryAdapter(), catalog=FixtureCatalogPricingAdapter()
    )

    class _Parser:
        def parse(self, text: str) -> ParsedPreference:
            return ParsedPreference(item_id="x", attributes={}, confirmation="ok")

    app = create_app(
        parser=_Parser(),
        engine=engine,
        messenger=FixtureMessenger(),
        user_chat_id="987654321",
    )
    return TestClient(app)


def test_health_endpoint_returns_readiness_without_leaking_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in _full_env(_orders_file(tmp_path)).items():
        monkeypatch.setenv(key, value)

    response = _make_app().get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["walmart_configured"] is True
    assert body["anthropic_configured"] is True
    # The readiness report is booleans only - no secret value in the payload.
    assert SECRET_API_KEY not in response.text
    assert "PRIVATE KEY" not in response.text
