"""GL-1: preflight config `doctor` command.

Pure config validation - no network calls, no real services. The check logic is
a pure function over an env mapping, so most tests pass a dict directly; a couple
exercise the CLI entry and the `python -m cartright` module entry.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from cartright.cli import main, run
from cartright.preflight import CheckResult, run_doctor_checks

# Sentinel secret values: these must NEVER appear in doctor output.
SECRET_API_KEY = "sk-ant-DOCTORSECRET12345"
SECRET_AUTH_TOKEN = "twilioAUTHSECRET67890"
SECRET_SID = "ACdoctorsecretsidvalue"
SECRET_CONSUMER_ID = "11111111-2222-3333-4444-secretconsumer"


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
        "TWILIO_ACCOUNT_SID": SECRET_SID,
        "TWILIO_AUTH_TOKEN": SECRET_AUTH_TOKEN,
        "TWILIO_FROM_NUMBER": "+15550001111",
        "WM_CONSUMER_ID": SECRET_CONSUMER_ID,
        "WM_PRIVATE_KEY": _pem_key(),
        "CARTRIGHT_USER_NUMBER": "+15555550123",
        "CARTRIGHT_ORDER_HISTORY_PATH": orders_path,
        "CARTRIGHT_REVIEW_BASE_URL": "https://cartright.example.com/review",
    }


def _orders_file(tmp_path: Path) -> str:
    path = tmp_path / "orders.json"
    path.write_text("[]", encoding="utf-8")
    return str(path)


def _failed(results: list[CheckResult], name: str) -> bool:
    return any(r.name == name and not r.ok for r in results)


def test_passes_with_a_full_valid_env(tmp_path: Path) -> None:
    results = run_doctor_checks(_full_env(_orders_file(tmp_path)))

    assert results, "expected check results"
    assert all(r.ok for r in results), [r for r in results if not r.ok]


def test_each_missing_required_var_fails(tmp_path: Path) -> None:
    base = _full_env(_orders_file(tmp_path))
    for var in [
        "ANTHROPIC_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "WM_CONSUMER_ID",
        "WM_PRIVATE_KEY",
        "CARTRIGHT_USER_NUMBER",
        "CARTRIGHT_ORDER_HISTORY_PATH",
        "CARTRIGHT_REVIEW_BASE_URL",
    ]:
        env = dict(base)
        del env[var]
        assert _failed(run_doctor_checks(env), var), f"{var} missing should fail"


def test_malformed_private_key_fails(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    env["WM_PRIVATE_KEY"] = "not-a-real-key"

    assert _failed(run_doctor_checks(env), "WM_PRIVATE_KEY")


def test_non_e164_phone_numbers_fail(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    env["CARTRIGHT_USER_NUMBER"] = "5551234"
    env["TWILIO_FROM_NUMBER"] = "555-000-1111"

    results = run_doctor_checks(env)

    assert _failed(results, "CARTRIGHT_USER_NUMBER")
    assert _failed(results, "TWILIO_FROM_NUMBER")


def test_missing_order_history_file_fails(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    env["CARTRIGHT_ORDER_HISTORY_PATH"] = str(tmp_path / "does-not-exist.json")

    assert _failed(run_doctor_checks(env), "CARTRIGHT_ORDER_HISTORY_PATH")


def test_non_https_review_url_fails(tmp_path: Path) -> None:
    env = _full_env(_orders_file(tmp_path))
    env["CARTRIGHT_REVIEW_BASE_URL"] = "http://insecure.example.com/review"

    assert _failed(run_doctor_checks(env), "CARTRIGHT_REVIEW_BASE_URL")


def test_report_never_prints_secret_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _full_env(_orders_file(tmp_path))
    _set_env(monkeypatch, env)

    main(["doctor"])

    out = capsys.readouterr().out
    for secret in (SECRET_API_KEY, SECRET_AUTH_TOKEN, SECRET_SID, SECRET_CONSUMER_ID):
        assert secret not in out, "doctor output leaked a secret value"
    # The private key body must never appear either.
    assert "PRIVATE KEY" not in out


def test_main_doctor_returns_zero_on_full_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, _full_env(_orders_file(tmp_path)))

    assert main(["doctor"]) == 0


def test_main_doctor_returns_nonzero_when_misconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ANTHROPIC_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "WM_CONSUMER_ID",
        "WM_PRIVATE_KEY",
        "CARTRIGHT_USER_NUMBER",
        "CARTRIGHT_ORDER_HISTORY_PATH",
        "CARTRIGHT_REVIEW_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    assert main(["doctor"]) == 1


def test_main_without_subcommand_is_a_usage_error() -> None:
    assert main([]) == 2


def test_run_loads_missing_var_from_local_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run` fills a var that is absent from the environment from the cwd .env."""
    monkeypatch.delenv("CARTRIGHT_USER_NUMBER", raising=False)
    (tmp_path / ".env").write_text("CARTRIGHT_USER_NUMBER=+15555550199\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    run(["doctor"])  # return code irrelevant; we assert the load side effect

    assert os.environ["CARTRIGHT_USER_NUMBER"] == "+15555550199"


def test_run_does_not_override_a_set_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real environment variable (e.g. a host secret) wins over the .env."""
    monkeypatch.setenv("CARTRIGHT_USER_NUMBER", "+15550000001")
    (tmp_path / ".env").write_text("CARTRIGHT_USER_NUMBER=+19999999999\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    run(["doctor"])

    assert os.environ["CARTRIGHT_USER_NUMBER"] == "+15550000001"


def test_module_entry_runs_doctor() -> None:
    """`python -m cartright doctor` works and reports failure with no config."""
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("WM_", "TWILIO_", "CARTRIGHT_", "ANTHROPIC_"))
    }
    proc = subprocess.run(
        [sys.executable, "-m", "cartright", "doctor"],
        env=clean,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1


def _set_env(monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str]) -> None:
    for var in (
        "ANTHROPIC_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "WM_CONSUMER_ID",
        "WM_KEY_VERSION",
        "WM_PUBLISHER_ID",
        "WM_PRIVATE_KEY",
        "CARTRIGHT_USER_NUMBER",
        "CARTRIGHT_ORDER_HISTORY_PATH",
        "CARTRIGHT_REVIEW_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
