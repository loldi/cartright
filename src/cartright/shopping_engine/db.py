from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    item_id TEXT PRIMARY KEY,
    attributes TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('inferred', 'explicit')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    sent INTEGER NOT NULL CHECK (sent IN (0, 1)),
    reason TEXT NOT NULL,
    body TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
