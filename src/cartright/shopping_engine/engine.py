from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cartright.shopping_engine.adapters.base import CatalogPricingAdapter, OrderHistoryAdapter
from cartright.shopping_engine.db import init_schema


@dataclass(frozen=True)
class ReorderCandidate:
    item_id: str
    window_start: str
    window_end: str


@dataclass(frozen=True)
class DealEvaluation:
    item_id: str
    is_deal: bool
    price: float | None


@dataclass(frozen=True)
class Cart:
    items: list[dict[str, Any]]
    total: float


@dataclass(frozen=True)
class Preference:
    item_id: str
    attributes: dict[str, Any]
    source: str  # "inferred" or "explicit"


class ShoppingEngine:
    """The single deterministic seam between the LLM layer and everything else.

    Owns its own SQLite persistence internally - callers only ever see the
    methods below, never the database.
    """

    def __init__(
        self,
        order_history: OrderHistoryAdapter,
        catalog: CatalogPricingAdapter,
        db_path: str | Path = ":memory:",
    ) -> None:
        self._order_history = order_history
        self._catalog = catalog
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        init_schema(self._conn)

    def getReorderCandidates(self) -> list[ReorderCandidate]:
        raise NotImplementedError

    def evaluateDeal(self, item_id: str) -> DealEvaluation:
        raise NotImplementedError

    def buildCart(self, item_ids: list[str]) -> Cart:
        raise NotImplementedError

    def recordPreference(
        self, item_id: str, attributes: dict[str, Any], source: str = "explicit"
    ) -> Preference:
        existing = self.getPreference(item_id)
        if existing is not None and existing.source == "explicit" and source != "explicit":
            # An explicit preference is the user's stated intent; nothing the
            # engine merely inferred is allowed to override it.
            return existing
        self._conn.execute(
            "INSERT OR REPLACE INTO preferences (item_id, attributes, source) VALUES (?, ?, ?)",
            (item_id, json.dumps(attributes), source),
        )
        self._conn.commit()
        return Preference(item_id=item_id, attributes=attributes, source=source)

    def getPreference(self, item_id: str) -> Preference | None:
        row = self._conn.execute(
            "SELECT item_id, attributes, source FROM preferences WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return Preference(
            item_id=row["item_id"],
            attributes=json.loads(row["attributes"]),
            source=row["source"],
        )
