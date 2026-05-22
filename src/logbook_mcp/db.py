"""SQLite wrapper for the Logbook MCP server.

Phase 0: single table for marked moments.
Phase 0.5 adds sea_days and summaries.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence


class LogbookDB:
    """SQLite-backed logbook store."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        """Create tables if they don't exist (idempotent)."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS marked_moments (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                text      TEXT    NOT NULL,
                timestamp TEXT    NOT NULL,
                longitude REAL,
                latitude  REAL
            );
            """
        )

    def query(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql, tuple(params))
        return cur.fetchall()

    def insert(self, sql: str, params: Sequence = ()) -> int:
        """Run an INSERT and return the new row id."""
        cur = self._conn.execute(sql, tuple(params))
        self._conn.commit()
        row_id = cur.lastrowid
        if row_id is None:
            raise RuntimeError("INSERT did not return a lastrowid")
        return row_id

    def close(self) -> None:
        self._conn.close()
