"""The `cartright` operator CLI.

A thin command surface for going live and staying healthy. Subcommands are
verification artifacts that exercise one real seam at a time; this slice ships
`doctor`, a pure preflight check over the environment that makes no network
calls and never prints a secret value. Later go-live slices hang their own
check subcommands off the same dispatcher.

Run as `cartright <subcommand>` (console entry) or `python -m cartright <...>`.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
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

# Vars whose value is sensitive: the report confirms presence/validity only and
# must never echo the value itself.
_SECRET = {"ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "WM_CONSUMER_ID"}


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


def format_report(results: Sequence[CheckResult]) -> str:
    """Render the checks as a grouped, secret-free table with an overall verdict."""
    lines: list[str] = ["Cartright preflight (doctor)", ""]
    width = max((len(r.name) for r in results), default=0)
    last_group = None
    for r in results:
        if r.group != last_group:
            lines.append(f"[{r.group}]")
            last_group = r.group
        mark = "PASS" if r.ok else "FAIL"
        # Belt-and-suspenders: a secret's value is never put in `detail`, but
        # never widen that contract here either.
        detail = "(hidden)" if r.name in _SECRET and not r.ok else r.detail
        lines.append(f"  {mark}  {r.name.ljust(width)}  {detail}")

    failed = [r for r in results if not r.ok]
    lines.append("")
    if failed:
        lines.append(f"{len(failed)} check(s) FAILED - fix the above before going live.")
    else:
        lines.append("All checks passed.")
    return "\n".join(lines)


def _doctor() -> int:
    results = run_doctor_checks(os.environ)
    print(format_report(results))
    return 1 if any(not r.ok for r in results) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cartright", description="Cartright operator CLI.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="Validate the runtime configuration (no network calls).")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()

    parser.print_usage()
    return 2
