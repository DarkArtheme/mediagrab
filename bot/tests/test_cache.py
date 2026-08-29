"""CacheRepository: roundtrip, upsert, delete, persistence, WAL mode."""

from pathlib import Path

import pytest

from reelsbot.cache import CachedItem, CachedPost, CacheRepository

POST = CachedPost(
    uid="DZu6cdBI2-A",
    provider="instagram",
    kind="reel",
    items=[CachedItem(kind="video", file_id="BAAC-video-id")],
    caption="a caption 🎬",
)


@pytest.fixture
def repo(tmp_path: Path) -> CacheRepository:
    return CacheRepository(tmp_path / "cache.sqlite3")


def test_roundtrip(repo: CacheRepository) -> None:
    repo.put(POST)
    assert repo.get("DZu6cdBI2-A") == POST


def test_missing_returns_none(repo: CacheRepository) -> None:
    assert repo.get("nope") is None


def test_multi_item_order_preserved(repo: CacheRepository) -> None:
    items = [
        CachedItem(kind="photo", file_id="p1"),
        CachedItem(kind="video", file_id="v1"),
        CachedItem(kind="photo", file_id="p2"),
    ]
    post = CachedPost(uid="ABC", provider="instagram", kind="post", items=items, caption="")
    repo.put(post)
    got = repo.get("ABC")
    assert got is not None
    assert got.items == items


def test_put_upserts(repo: CacheRepository) -> None:
    repo.put(POST)
    updated = CachedPost(
        uid=POST.uid,
        provider=POST.provider,
        kind=POST.kind,
        items=[CachedItem(kind="video", file_id="new-id")],
        caption="new caption",
    )
    repo.put(updated)
    assert repo.get(POST.uid) == updated


def test_delete(repo: CacheRepository) -> None:
    repo.put(POST)
    repo.delete(POST.uid)
    assert repo.get(POST.uid) is None
    repo.delete(POST.uid)  # deleting a missing row is a no-op


def test_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "cache.sqlite3"
    first = CacheRepository(db)
    first.put(POST)
    first.close()
    second = CacheRepository(db)
    assert second.get(POST.uid) == POST


def test_wal_mode(repo: CacheRepository) -> None:
    assert repo._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
