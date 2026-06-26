"""Slice 7: the JSON-file order-history adapter.

Exercises the real adapter against on-disk JSON fixtures only - it has no
dependency on the excluded self-scrape utility, just on the shape it produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cartright.shopping_engine import ShoppingEngine
from cartright.shopping_engine.adapters.fixtures import FixtureCatalogPricingAdapter
from cartright.shopping_engine.adapters.order_history import JsonFileOrderHistoryAdapter

ORDERS = [
    {"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-01"},
    {"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-11"},
    {"item_id": "37774610", "title": "Coffee", "ordered_at": "2026-06-02"},
]


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "orders.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_from_file_reads_all_orders(tmp_path: Path) -> None:
    adapter = JsonFileOrderHistoryAdapter.from_file(_write(tmp_path, ORDERS))

    assert adapter.get_orders() == ORDERS


def test_get_orders_filters_by_item_id(tmp_path: Path) -> None:
    adapter = JsonFileOrderHistoryAdapter.from_file(_write(tmp_path, ORDERS))

    coffee = adapter.get_orders("37774610")

    assert [o["item_id"] for o in coffee] == ["37774610"]


def test_unknown_item_id_returns_empty_list(tmp_path: Path) -> None:
    adapter = JsonFileOrderHistoryAdapter.from_file(_write(tmp_path, ORDERS))

    assert adapter.get_orders("does-not-exist") == []


def test_non_array_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        JsonFileOrderHistoryAdapter.from_file(_write(tmp_path, {"not": "a list"}))


def test_from_env_reads_path_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, ORDERS)
    monkeypatch.setenv("CARTRIGHT_ORDER_HISTORY_PATH", str(path))

    adapter = JsonFileOrderHistoryAdapter.from_env()

    assert adapter.get_orders() == ORDERS


def test_real_adapter_drops_into_the_engine_unchanged(tmp_path: Path) -> None:
    # Two purchases each: enough for the engine to infer a reorder cadence.
    orders = ORDERS + [{"item_id": "37774610", "title": "Coffee", "ordered_at": "2026-06-12"}]
    adapter = JsonFileOrderHistoryAdapter.from_file(_write(tmp_path, orders))
    engine = ShoppingEngine(order_history=adapter, catalog=FixtureCatalogPricingAdapter())

    candidates = {c.item_id for c in engine.getReorderCandidates()}

    # Both repeat-purchased items yield reorder candidates from real file data.
    assert candidates == {"10295020", "37774610"}
