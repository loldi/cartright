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
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TextIO
from urllib.parse import urlparse

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import (
    CatalogPricingAdapter,
    OrderHistoryAdapter,
    TwilioAdapter,
)
from cartright.shopping_engine.adapters.fixtures import FixtureCatalogPricingAdapter
from cartright.shopping_engine.adapters.order_history import JsonFileOrderHistoryAdapter
from cartright.shopping_engine.adapters.twilio_sms import TwilioSmsAdapter
from cartright.shopping_engine.adapters.walmart import (
    WalmartCatalogPricingAdapter,
    _load_private_key,
)

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


def _sanitized_error(label: str, exc: Exception) -> str:
    """A one-line, secret-free description of a failed live call.

    Deliberately uses only the exception class name and (if present) an HTTP
    status code - never `str(exc)`, which for httpx carries the request URL and
    for a Twilio error embeds the Account SID. Headers (the walmart signature,
    Twilio basic auth) are never touched.
    """
    detail = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if isinstance(status, int):
        detail += f" (HTTP {status})"
    return f"{label}: {detail}. Re-run `cartright doctor` and verify the relevant secrets."


def catalog_check(adapter: CatalogPricingAdapter, item_id: str, out: TextIO = sys.stdout) -> int:
    """GL-2: one real walmart.io Product Lookup, printed as the engine sees it."""
    try:
        price = adapter.get_price(item_id)
    except Exception as exc:  # noqa: BLE001 - report any live failure, never crash
        print(_sanitized_error("walmart.io lookup failed", exc), file=out)
        return 1

    if not price:
        print(
            f"No result for item {item_id!r}. Either the item is unavailable, or the "
            "credentials/signature were rejected. Try a known-valid item id; if it "
            "still fails, re-run `cartright doctor` and check your WM_* values.",
            file=out,
        )
        return 1

    print(f"Item {price.get('item_id', item_id)}: {price.get('title', '')}", file=out)
    print(f"  in_stock:  {price.get('in_stock')}", file=out)
    if "price" in price:
        print(f"  price:     ${price['price']:.2f}", file=out)
    if "was_price" in price:
        print(f"  was_price: ${price['was_price']:.2f}", file=out)
    return 0


def _validate_orders(orders: list[dict[str, object]]) -> list[str]:
    """Return one problem string per malformed order row (by zero-based index)."""
    problems: list[str] = []
    for i, order in enumerate(orders):
        item_id = order.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip():
            problems.append(f"row {i}: missing/empty item_id")
        if not isinstance(order.get("title"), str):
            problems.append(f"row {i}: missing/non-string title")
        ordered_at = order.get("ordered_at")
        try:
            date.fromisoformat(str(ordered_at))
        except ValueError:
            problems.append(f"row {i}: ordered_at is not an ISO date ({ordered_at!r})")
    return problems


def orders_check(adapter: OrderHistoryAdapter, out: TextIO = sys.stdout) -> int:
    """GL-3: validate the real order-history file and show inferred candidates."""
    orders = adapter.get_orders()
    if not orders:
        print("No orders found - the order-history file is empty.", file=out)
        return 1

    print(f"Loaded {len(orders)} order record(s).", file=out)
    problems = _validate_orders(orders)
    if problems:
        print(f"\n{len(problems)} malformed row(s):", file=out)
        for problem in problems:
            print(f"  - {problem}", file=out)
        return 1

    # Candidate inference never prices anything, so a fixture catalog stands in
    # for the unused catalog seam (same approach as scripts/dump_candidates.py).
    engine = ShoppingEngine(order_history=adapter, catalog=FixtureCatalogPricingAdapter())
    candidates = engine.getReorderCandidates()
    print(f"\n{len(candidates)} reorder candidate(s):", file=out)
    for c in candidates:
        print(f"  [{c.item_id}] {c.title}: {c.window_start} .. {c.window_end}", file=out)
    return 0


def sms_check(twilio: TwilioAdapter, to: str, out: TextIO = sys.stdout) -> int:
    """GL-4: send one real test SMS to confirm the Twilio wiring works."""
    body = "Cartright test message - if you got this, your SMS wiring works."
    try:
        twilio.send_sms(to=to, body=body)
    except Exception as exc:  # noqa: BLE001 - report any live failure, never crash
        print(_sanitized_error("SMS send failed", exc), file=out)
        return 1
    print(f"Sent test SMS to {to}.", file=out)
    return 0


def _catalog_check_cmd(item_id: str) -> int:  # pragma: no cover - thin from_env wiring
    return catalog_check(WalmartCatalogPricingAdapter.from_env(), item_id)


def _orders_check_cmd() -> int:  # pragma: no cover - thin from_env wiring
    return orders_check(JsonFileOrderHistoryAdapter.from_env())


def _sms_check_cmd(to: str) -> int:  # pragma: no cover - thin from_env wiring
    return sms_check(TwilioSmsAdapter.from_env(), to)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cartright", description="Cartright operator CLI.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="Validate the runtime configuration (no network calls).")
    cat = sub.add_parser("catalog-check", help="Live walmart.io price lookup for one item.")
    cat.add_argument("item_id", help="Walmart catalog item id to look up.")
    sub.add_parser("orders-check", help="Validate the order-history file and show candidates.")
    sms = sub.add_parser("sms-check", help="Send one real test SMS via Twilio.")
    sms.add_argument("to", help="Destination phone number (E.164, e.g. +15555550123).")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command == "catalog-check":
        return _catalog_check_cmd(args.item_id)
    if args.command == "orders-check":
        return _orders_check_cmd()
    if args.command == "sms-check":
        return _sms_check_cmd(args.to)

    parser.print_usage()
    return 2
