from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cartright.shopping_engine.adapters.base import OrderHistoryAdapter


class JsonFileOrderHistoryAdapter(OrderHistoryAdapter):
    """Reads past orders from a structured JSON file on disk.

    The file is the output of the user's private, one-time self-scrape utility,
    which is deliberately NOT part of this repo (see README). This adapter has no
    knowledge of how the file was produced - it only consumes the already-
    structured result. Expected shape: a JSON array of objects, each with at
    least `item_id`, `title`, and `ordered_at` (ISO date string), e.g.:

        [{"item_id": "10295020", "title": "Paper Towels", "ordered_at": "2026-06-01"}]
    """

    def __init__(self, orders: list[dict[str, Any]]) -> None:
        self._orders = orders

    @classmethod
    def from_file(cls, path: str | Path) -> JsonFileOrderHistoryAdapter:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("order-history file must contain a JSON array of orders")
        return cls(data)

    @classmethod
    def from_env(cls) -> JsonFileOrderHistoryAdapter:
        """Production constructor: path comes from `CARTRIGHT_ORDER_HISTORY_PATH`."""
        return cls.from_file(os.environ["CARTRIGHT_ORDER_HISTORY_PATH"])

    def get_orders(self, item_id: str | None = None) -> list[dict[str, Any]]:
        if item_id is None:
            return list(self._orders)
        return [order for order in self._orders if order.get("item_id") == item_id]
