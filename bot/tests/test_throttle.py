"""ExtractionGate: per-user single job, concurrency cap, spaced-out starts."""

import asyncio
from time import monotonic

from reelsbot.throttle import ExtractionGate


class TestUserGate:
    def test_second_job_refused(self) -> None:
        gate = ExtractionGate()
        assert gate.acquire_user(1) is True
        assert gate.acquire_user(1) is False

    def test_release_allows_next_job(self) -> None:
        gate = ExtractionGate()
        gate.acquire_user(1)
        gate.release_user(1)
        assert gate.acquire_user(1) is True

    def test_users_are_independent(self) -> None:
        gate = ExtractionGate()
        assert gate.acquire_user(1) is True
        assert gate.acquire_user(2) is True

    def test_release_unknown_user_is_noop(self) -> None:
        ExtractionGate().release_user(42)


class TestSlot:
    async def test_min_interval_between_starts(self) -> None:
        gate = ExtractionGate(max_concurrent=2, min_interval=0.05)
        starts: list[float] = []

        async def job() -> None:
            async with gate.slot():
                starts.append(monotonic())

        await asyncio.gather(job(), job())
        assert starts[1] - starts[0] >= 0.045

    async def test_concurrency_capped(self) -> None:
        gate = ExtractionGate(max_concurrent=1, min_interval=0.0)
        running = 0
        peak = 0

        async def job() -> None:
            nonlocal running, peak
            async with gate.slot():
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.01)
                running -= 1

        await asyncio.gather(*(job() for _ in range(3)))
        assert peak == 1

    async def test_no_interval_no_waiting(self) -> None:
        gate = ExtractionGate(max_concurrent=2, min_interval=0.0)
        start = monotonic()
        for _ in range(3):
            async with gate.slot():
                pass
        assert monotonic() - start < 0.05


class TestWaitIdle:
    async def test_idle_gate_returns_immediately(self) -> None:
        gate = ExtractionGate()
        assert gate.busy_count() == 0
        assert await gate.wait_idle(timeout=0.01) is True

    async def test_waits_for_job_to_finish(self) -> None:
        gate = ExtractionGate()
        gate.acquire_user(1)
        assert gate.busy_count() == 1

        async def finish_soon() -> None:
            await asyncio.sleep(0.02)
            gate.release_user(1)

        task = asyncio.create_task(finish_soon())
        assert await gate.wait_idle(timeout=1.0, poll_interval=0.005) is True
        await task

    async def test_timeout_with_stuck_job(self) -> None:
        gate = ExtractionGate()
        gate.acquire_user(1)
        assert await gate.wait_idle(timeout=0.02, poll_interval=0.005) is False
        assert gate.busy_count() == 1
