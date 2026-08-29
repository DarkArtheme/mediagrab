"""Politeness controls that protect the burner Instagram account: a global cap
on concurrent extractions, a minimum interval between extraction starts, and at
most one in-flight job per user."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

MAX_CONCURRENT_EXTRACTIONS = 2
MIN_EXTRACTION_INTERVAL = 3.0


class ExtractionGate:
    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_EXTRACTIONS,
        min_interval: float = MIN_EXTRACTION_INTERVAL,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._interval_lock = asyncio.Lock()
        self._min_interval = min_interval
        self._next_allowed = 0.0
        self._busy_users: set[int] = set()

    def acquire_user(self, user_id: int) -> bool:
        """Claim the per-user job slot; False means a job is already running."""
        if user_id in self._busy_users:
            return False
        self._busy_users.add(user_id)
        return True

    def release_user(self, user_id: int) -> None:
        self._busy_users.discard(user_id)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold an extraction slot: bounded concurrency, spaced-out starts."""
        async with self._semaphore:
            async with self._interval_lock:
                wait = self._next_allowed - monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._next_allowed = monotonic() + self._min_interval
            yield
