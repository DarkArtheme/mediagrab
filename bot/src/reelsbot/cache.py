"""SQLite repository for the uid → Telegram file_id cache.

All DB access goes through :class:`CacheRepository` so a later Postgres
migration touches this one module.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from mediagrab.models import MediaKind

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    uid        TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    file_ids   TEXT NOT NULL,
    caption    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


@dataclass(frozen=True, slots=True)
class CachedItem:
    """One already-uploaded media file, addressable by its Telegram file_id."""

    kind: MediaKind
    file_id: str


@dataclass(frozen=True, slots=True)
class CachedPost:
    """A previously delivered post: re-sendable without touching the platform."""

    uid: str
    provider: str
    kind: str
    items: list[CachedItem]
    caption: str


class CacheRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, uid: str) -> CachedPost | None:
        row = self._conn.execute(
            "SELECT provider, kind, file_ids, caption FROM posts WHERE uid = ?", (uid,)
        ).fetchone()
        if row is None:
            return None
        provider, kind, file_ids, caption = row
        items = [CachedItem(kind=e["kind"], file_id=e["file_id"]) for e in json.loads(file_ids)]
        return CachedPost(uid=uid, provider=provider, kind=kind, items=items, caption=caption)

    def put(self, post: CachedPost) -> None:
        file_ids = json.dumps([{"kind": i.kind, "file_id": i.file_id} for i in post.items])
        self._conn.execute(
            "INSERT INTO posts (uid, provider, kind, file_ids, caption)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(uid) DO UPDATE SET provider = excluded.provider,"
            " kind = excluded.kind, file_ids = excluded.file_ids, caption = excluded.caption",
            (post.uid, post.provider, post.kind, file_ids, post.caption),
        )
        self._conn.commit()

    def delete(self, uid: str) -> None:
        self._conn.execute("DELETE FROM posts WHERE uid = ?", (uid,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
