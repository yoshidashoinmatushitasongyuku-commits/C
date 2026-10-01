"""処理済み ASIN の履歴（SQLite）。同じ商品を何度も投稿しないために使う。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("amazon_affiliate.history")


class ProcessedHistory:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_asins (
                asin TEXT PRIMARY KEY,
                title TEXT,
                first_processed_at TEXT NOT NULL,
                last_processed_at TEXT NOT NULL,
                process_count INTEGER NOT NULL DEFAULT 1,
                output_file TEXT
            )
            """
        )
        self.conn.commit()

    def is_processed(self, asin: str, reprocess_after_days: int | None) -> bool:
        row = self.conn.execute(
            "SELECT last_processed_at FROM processed_asins WHERE asin = ?", (asin,)
        ).fetchone()
        if row is None:
            return False
        if reprocess_after_days is None:
            return True
        last = datetime.fromisoformat(row[0])
        return datetime.now(timezone.utc) - last < timedelta(days=reprocess_after_days)

    def mark_processed(self, asin: str, title: str, output_file: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO processed_asins (asin, title, first_processed_at, last_processed_at, output_file)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(asin) DO UPDATE SET
                title = excluded.title,
                last_processed_at = excluded.last_processed_at,
                process_count = process_count + 1,
                output_file = excluded.output_file
            """,
            (asin, title, now, now, output_file),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
