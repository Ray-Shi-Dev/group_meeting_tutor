# -*- coding: utf-8 -*-
"""Processing state (SQLite). Dedupe is by post id: a deck re-posted the next week is summarized again."""

from __future__ import annotations

import sqlite3
import time
from typing import Optional

# Final states: later runs skip these posts.
FINAL_STATUSES = ("done", "permission_notified", "skipped_opt_out", "blocked_injection")


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS posts (
                   post_id TEXT PRIMARY KEY,
                   status TEXT NOT NULL,
                   reply_id TEXT,
                   provider TEXT,
                   detail TEXT,
                   processed_at INTEGER NOT NULL
               )"""
        )
        self.conn.commit()

    def status(self, post_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT status FROM posts WHERE post_id=?", (post_id,)).fetchone()
        return row[0] if row else None

    def is_final(self, post_id: str) -> bool:
        return self.status(post_id) in FINAL_STATUSES

    def record(
        self, post_id: str, status: str, reply_id: str = "", provider: str = "", detail: str = ""
    ) -> None:
        self.conn.execute(
            "INSERT INTO posts(post_id,status,reply_id,provider,detail,processed_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET status=excluded.status, reply_id=excluded.reply_id, "
            "provider=excluded.provider, detail=excluded.detail, processed_at=excluded.processed_at",
            (post_id, status, reply_id, provider, detail, int(time.time())),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
