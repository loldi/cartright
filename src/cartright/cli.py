"""The `cartright` operator CLI.

A thin command surface for going live and staying healthy. Subcommands are
verification artifacts that exercise one real seam at a time; this slice ships
`doctor`, a pure preflight check over the environment that makes no network
calls and never prints a secret value. Later go-live slices hang their own
check subcommands off the same dispatcher.

Run as `cartright <subcommand>` (console entry) or `python -m cartright <...>`.

On startup the CLI loads a local `.env` (if present) so the operator can run
checks against a populated `.env` instead of exporting every var by hand. Real
environment variables (e.g. host secrets) always win - `.env` only fills gaps.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from typing import TextIO

from dotenv import find_dotenv, load_dotenv

from cartright.llm.alerts import AlertComposer
from cartright.preflight import CheckResult, run_doctor_checks
from cartright.scheduler import run_alert_cycle_detailed
from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.base import (
    CatalogPricingAdapter,
    Messenger,
    OrderHistoryAdapter,
)
from cartright.shopping_engine.adapters.fixtures import FixtureCatalogPricingAdapter
from cartright.shopping_engine.adapters.order_history import JsonFileOrderHistoryAdapter
from cartright.shopping_engine.adapters.telegram import TelegramMessenger
from cartright.shopping_engine.adapters.walmart import WalmartCatalogPricingAdapter

# Vars whose value is sensitive: the report confirms presence/validity only and
# must never echo the value itself.
_SECRET = {"ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "WM_CONSUMER_ID"}


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
    status code - never `str(exc)`, which for httpx carries the request URL
    (the Telegram bot token lives in that URL). Headers (the walmart signature)
    are never touched.
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


def message_check(messenger: Messenger, to: str, out: TextIO = sys.stdout) -> int:
    """GL-4: send one real test message to confirm the Telegram wiring works."""
    body = "Cartright test message - if you got this, your messaging wiring works."
    try:
        messenger.send_message(to=to, body=body)
    except Exception as exc:  # noqa: BLE001 - report any live failure, never crash
        print(_sanitized_error("Message send failed", exc), file=out)
        return 1
    print(f"Sent test message to chat {to}.", file=out)
    return 0


def alert_once(
    engine: ShoppingEngine,
    composer: AlertComposer,
    messenger: Messenger,
    *,
    user_chat_id: str,
    today: date | None = None,
    out: TextIO = sys.stdout,
) -> int:
    """GL-7: run a single alert cycle now and report what it sent vs skipped.

    Drives verification and the demo recording without waiting for the hourly
    scheduler tick (PRD: only the timing is staged, the content stays live).
    """
    outcomes = run_alert_cycle_detailed(
        engine=engine,
        composer=composer,
        messenger=messenger,
        user_chat_id=user_chat_id,
        today=today,
    )
    sent = [o for o in outcomes if o.sent]
    print(f"Ran one alert cycle: {len(sent)} sent, {len(outcomes) - len(sent)} skipped.", file=out)
    for o in outcomes:
        mark = "SENT" if o.sent else "skip"
        print(f"  [{mark}] [{o.item_id}] {o.title}: {o.reason}", file=out)
    return 0


def decisions(engine: ShoppingEngine, limit: int = 20, out: TextIO = sys.stdout) -> int:
    """Print the persisted audit trail: why each recent candidate was sent or skipped.

    Every real scheduler cycle and every `alert-once` run persists one row per
    candidate via `ShoppingEngine.recordDecision`; this surfaces that history.
    """
    entries = engine.getDecisionLog(limit=limit)
    if not entries:
        print("No decisions recorded yet.", file=out)
        return 0
    for e in entries:
        mark = "SENT" if e.sent else "skip"
        print(f"{e.recorded_at}  [{mark}]  [{e.item_id}] {e.title}: {e.reason}", file=out)
    return 0


def _catalog_check_cmd(item_id: str) -> int:  # pragma: no cover - thin from_env wiring
    return catalog_check(WalmartCatalogPricingAdapter.from_env(), item_id)


def _orders_check_cmd() -> int:  # pragma: no cover - thin from_env wiring
    return orders_check(JsonFileOrderHistoryAdapter.from_env())


def _message_check_cmd(to: str | None) -> int:  # pragma: no cover - thin from_env wiring
    chat_id = to or os.environ["CARTRIGHT_USER_CHAT_ID"]
    return message_check(TelegramMessenger.from_env(), chat_id)


def _alert_once_cmd() -> int:  # pragma: no cover - thin from_env wiring
    from cartright.llm.claude import ClaudeAlertComposer
    from cartright.main import build_engine

    return alert_once(
        build_engine(),
        ClaudeAlertComposer(),
        TelegramMessenger.from_env(),
        user_chat_id=os.environ["CARTRIGHT_USER_CHAT_ID"],
    )


def _decisions_cmd(limit: int) -> int:  # pragma: no cover - thin from_env wiring
    from cartright.main import build_engine

    return decisions(build_engine(), limit=limit)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cartright", description="Cartright operator CLI.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="Validate the runtime configuration (no network calls).")
    cat = sub.add_parser("catalog-check", help="Live walmart.io price lookup for one item.")
    cat.add_argument("item_id", help="Walmart catalog item id to look up.")
    sub.add_parser("orders-check", help="Validate the order-history file and show candidates.")
    msg = sub.add_parser("message-check", help="Send one real test message via Telegram.")
    msg.add_argument(
        "to",
        nargs="?",
        default=None,
        help="Destination Telegram chat id (defaults to CARTRIGHT_USER_CHAT_ID).",
    )
    sub.add_parser("alert-once", help="Run one proactive alert cycle now and report it.")
    dec = sub.add_parser("decisions", help="Show the audited history of sent/skipped alerts.")
    dec.add_argument(
        "--limit", type=int, default=20, help="Max rows to show, most recent first (default 20)."
    )

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command == "catalog-check":
        return _catalog_check_cmd(args.item_id)
    if args.command == "orders-check":
        return _orders_check_cmd()
    if args.command == "message-check":
        return _message_check_cmd(args.to)
    if args.command == "alert-once":
        return _alert_once_cmd()
    if args.command == "decisions":
        return _decisions_cmd(args.limit)

    parser.print_usage()
    return 2


def run(argv: Sequence[str] | None = None) -> int:
    """Console / module entry point: load the project-dir `.env`, then dispatch.

    Operators run `cartright <cmd>` from the project directory, so we load that
    directory's `.env` (walking up to the repo root) before reading any var.
    Host environment variables still win: `load_dotenv` does not override a var
    that is already set, so Render secrets take precedence over a stray `.env`.
    `main()` itself stays free of this I/O so it remains hermetically testable.
    """
    load_dotenv(find_dotenv(usecwd=True))
    return main(argv)
