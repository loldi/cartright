"""Config introspection shared by the operator CLI and the web service.

Pure, secret-free, no network calls: an env mapping in, structured results out.
`run_doctor_checks` powers the `cartright doctor` command; `readiness` powers the
deployed service's `/health` report. Both live here (not in `cli.py`) so the web
layer can reuse them without importing the operator CLI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from cartright.shopping_engine.adapters.walmart import _load_private_key

# Required env vars grouped for a readable report. Optional vars (WM_KEY_VERSION,
# WM_PUBLISHER_ID, CARTRIGHT_DB_PATH, CARTRIGHT_RUN_SCHEDULER, ...) all have safe
# defaults and so are deliberately not gated here.
_REQUIRED = {
    "Claude": ["ANTHROPIC_API_KEY"],
    "Twilio": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
    "walmart.io": ["WM_CONSUMER_ID", "WM_PRIVATE_KEY"],
    "Cartright": [
        "CARTRIGHT_USER_NUMBER",
        "CARTRIGHT_ORDER_HISTORY_PATH",
        "CARTRIGHT_REVIEW_BASE_URL",
    ],
}


@dataclass(frozen=True)
class CheckResult:
    group: str
    name: str
    ok: bool
    detail: str  # human-readable; never contains a secret value


def _is_e164(value: str) -> bool:
    digits = value[1:]
    return value.startswith("+") and digits.isdigit() and 1 <= len(digits) <= 15


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def run_doctor_checks(env: Mapping[str, str]) -> list[CheckResult]:
    """Validate the runtime config. Pure: an env mapping in, results out.

    Beyond presence, applies the format checks that catch the mistakes that only
    bite at boot or on the first live call: an unparseable signing key, a phone
    number that isn't E.164, a missing order-history file, a non-https review URL.
    """
    results: list[CheckResult] = []

    for group, names in _REQUIRED.items():
        for name in names:
            present = bool(env.get(name, "").strip())
            results.append(CheckResult(group, name, present, "set" if present else "missing"))

    # WM_PRIVATE_KEY must actually parse as an RSA key (presence already recorded).
    raw_key = env.get("WM_PRIVATE_KEY", "").strip()
    if raw_key:
        try:
            key = _load_private_key(raw_key)
            detail = f"valid RSA {key.key_size}-bit private key"
            ok = True
        except Exception:
            detail = "present but not a valid PKCS#8 RSA key (PEM or base64 DER)"
            ok = False
        results.append(CheckResult("walmart.io", "WM_PRIVATE_KEY", ok, detail))

    for name in ("CARTRIGHT_USER_NUMBER", "TWILIO_FROM_NUMBER"):
        value = env.get(name, "").strip()
        if value:
            ok = _is_e164(value)
            results.append(
                CheckResult(
                    "Cartright" if name.startswith("CARTRIGHT") else "Twilio",
                    name,
                    ok,
                    "valid E.164 format" if ok else "not E.164 format (expected +<digits>)",
                )
            )

    path = env.get("CARTRIGHT_ORDER_HISTORY_PATH", "").strip()
    if path:
        ok = os.path.isfile(path) and os.access(path, os.R_OK)
        results.append(
            CheckResult(
                "Cartright",
                "CARTRIGHT_ORDER_HISTORY_PATH",
                ok,
                "found and readable" if ok else f"not found / unreadable: {path}",
            )
        )

    url = env.get("CARTRIGHT_REVIEW_BASE_URL", "").strip()
    if url:
        ok = _is_https_url(url)
        results.append(
            CheckResult(
                "Cartright",
                "CARTRIGHT_REVIEW_BASE_URL",
                ok,
                f"valid https URL ({url})" if ok else "not a valid https URL",
            )
        )

    return results


def readiness(env: Mapping[str, str]) -> dict[str, bool]:
    """A secret-free per-subsystem readiness report for the `/health` endpoint.

    Derived from `run_doctor_checks`, so a subsystem is "configured" only when
    all of its required vars are present AND well-formed. Returns booleans only -
    never a secret value, and never a live call.
    """
    results = run_doctor_checks(env)

    def configured(*names: str) -> bool:
        return all(
            any(r.name == n for r in results) and all(r.ok for r in results if r.name == n)
            for n in names
        )

    return {
        "anthropic_configured": configured("ANTHROPIC_API_KEY"),
        "twilio_configured": configured(
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"
        ),
        "walmart_configured": configured("WM_CONSUMER_ID", "WM_PRIVATE_KEY"),
        "order_history_present": configured("CARTRIGHT_ORDER_HISTORY_PATH"),
        "scheduler_enabled": env.get("CARTRIGHT_RUN_SCHEDULER") == "1",
    }
