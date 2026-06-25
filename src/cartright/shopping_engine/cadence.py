from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class ReorderWindow:
    start: date
    end: date


def _order_dates(orders: list[dict[str, Any]]) -> list[date]:
    return sorted(date.fromisoformat(o["ordered_at"]) for o in orders)


def infer_window(orders: list[dict[str, Any]]) -> ReorderWindow | None:
    """Infer a predicted reorder window from one item's past orders.

    Returns None when there aren't at least two orders - cadence can't be
    honestly inferred from a single data point. The window is centered on
    (last order + average gap); its half-width reflects how irregular the
    gaps were, with a one-day floor so a perfectly regular cadence still
    yields a real range.
    """
    dates = _order_dates(orders)
    if len(dates) < 2:
        return None

    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    avg_gap = round(sum(gaps) / len(gaps))
    margin = max(1, round((max(gaps) - min(gaps)) / 2))

    predicted = dates[-1] + timedelta(days=avg_gap)
    return ReorderWindow(
        start=predicted - timedelta(days=margin),
        end=predicted + timedelta(days=margin),
    )


def group_by_item(orders: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bucket order lines by their stable catalog identifier (`item_id`).

    `item_id` is the Walmart item ID (a 1:1 catalog key), not a human label -
    it's what the catalog/pricing adapter re-queries later. The human-readable
    product title lives separately on each order and can drift between orders
    of the same item; see `display_title`.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in orders:
        grouped[o["item_id"]].append(o)
    return grouped


def display_title(orders: list[dict[str, Any]], item_id: str) -> str:
    """Pick a human-readable title for an item from its most recent order.

    Walmart product titles drift over time, so the latest order's title is the
    freshest label to show the user. Falls back to the stable `item_id` when no
    title is present on the order data.
    """
    latest = max(orders, key=lambda o: o["ordered_at"])
    title = latest.get("title")
    return title if title else item_id
