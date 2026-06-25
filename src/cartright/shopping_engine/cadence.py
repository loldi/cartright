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
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for o in orders:
        grouped[o["item_id"]].append(o)
    return grouped
