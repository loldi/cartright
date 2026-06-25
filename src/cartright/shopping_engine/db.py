from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    item_id TEXT PRIMARY KEY,
    attributes TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('inferred', 'explicit')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
