"""main: startup temp-dir sweep and the graceful-shutdown hook."""

import asyncio
import sqlite3
from pathlib import Path

import pytest

from reelsbot import main
from reelsbot.cache import CacheRepository
from reelsbot.throttle import ExtractionGate


class TestSweepDownloadDir:
    def test_removes_only_known_prefixes(self, tmp_path: Path) -> None:
        (tmp_path / "ig-ABC-x1y2").mkdir()
        (tmp_path / "tt-123-z9").mkdir()
        (tmp_path / "keep-me").mkdir()
        (tmp_path / "notes.txt").write_text("unrelated")

        assert main.sweep_download_dir(tmp_path) == 2
        assert sorted(p.name for p in tmp_path.iterdir()) == ["keep-me", "notes.txt"]

    def test_none_dir_is_noop(self) -> None:
        assert main.sweep_download_dir(None) == 0

    def test_missing_dir_is_noop(self, tmp_path: Path) -> None:
        assert main.sweep_download_dir(tmp_path / "does-not-exist") == 0


class TestOnShutdown:
    async def test_waits_for_jobs_then_closes_cache(self, tmp_path: Path) -> None:
        gate = ExtractionGate()
        gate.acquire_user(1)
        cache = CacheRepository(tmp_path / "cache.sqlite3")

        async def finish_soon() -> None:
            await asyncio.sleep(0.02)
            gate.release_user(1)

        task = asyncio.create_task(finish_soon())
        await main.on_shutdown(gate, cache)
        await task

        assert gate.busy_count() == 0
        with pytest.raises(sqlite3.ProgrammingError):  # connection is closed
            cache.count()

    async def test_closes_cache_even_when_grace_expires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(main, "SHUTDOWN_GRACE", 0.02)
        gate = ExtractionGate()
        gate.acquire_user(1)  # never released — a stuck job
        cache = CacheRepository(tmp_path / "cache.sqlite3")

        await main.on_shutdown(gate, cache)

        with pytest.raises(sqlite3.ProgrammingError):
            cache.count()
