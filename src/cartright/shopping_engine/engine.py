from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cartright.shopping_engine.adapters.base import CatalogPricingAdapter, OrderHistoryAdapter
from cartright.shopping_engine.cadence import display_title, group_by_item, infer_window
from cartright.shopping_engine.db import init_schema
from cartright.shopping_engine.pricing import Cart, DealEvaluation, build_cart, evaluate_deal


@dataclass(frozen=True)
class ReorderCandidate:
    item_id: str  # stable Walmart catalog identifier; used to re-query pricing
    title: str  # human-readable product label for SMS / review UI
    window_start: str
    window_end: str


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
        # check_same_thread=False: the engine is a single-user, single-writer
        # store reached from FastAPI's request threadpool, so the connection is
        # touched from threads other than the one that created it.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        init_schema(self._conn)

    def getReorderCandidates(self) -> list[ReorderCandidate]:
        candidates: list[ReorderCandidate] = []
        grouped = group_by_item(self._order_history.get_orders())
        for item_id in sorted(grouped):
            window = infer_window(grouped[item_id])
            if window is None:
                continue
            candidates.append(
                ReorderCandidate(
                    item_id=item_id,
                    title=display_title(grouped[item_id], item_id),
                    window_start=window.start.isoformat(),
                    window_end=window.end.isoformat(),
                )
            )
        return candidates

    def evaluateDeal(self, item_id: str) -> DealEvaluation:
        return evaluate_deal(item_id, self._catalog.get_price(item_id))

    def buildCart(self, item_ids: list[str]) -> Cart:
        return build_cart(item_ids, self._catalog.get_price)

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
