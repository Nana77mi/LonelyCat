import asyncio
import time
from typing import List

from runtime.lane_queue import LaneQueue


def test_submit_interface_returns_value() -> None:
    async def run_test() -> None:
        queue = LaneQueue()
        result = await queue.submit("lane-a", lambda: 42)
        assert result == 42

    asyncio.run(run_test())


def test_same_lane_is_serial_and_fifo() -> None:
    async def run_test() -> None:
        queue = LaneQueue(max_concurrency=3)
        running = 0
        max_running = 0
        start_order: List[int] = []
        end_order: List[int] = []

        async def task(index: int) -> int:
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            start_order.append(index)
            await asyncio.sleep(0.01)
            running -= 1
            end_order.append(index)
            return index

        results = await asyncio.gather(
            queue.submit("lane-a", lambda: task(1)),
            queue.submit("lane-a", lambda: task(2)),
            queue.submit("lane-a", lambda: task(3)),
        )

        assert results == [1, 2, 3]
        assert start_order == [1, 2, 3]
        assert end_order == [1, 2, 3]
        assert max_running == 1

    asyncio.run(run_test())


def test_different_lanes_can_overlap() -> None:
    async def run_test() -> None:
        queue = LaneQueue(max_concurrency=2)
        running = 0
        max_running = 0

        async def task() -> None:
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.06)
            running -= 1

        start = time.monotonic()
        await asyncio.gather(
            queue.submit("lane-a", task),
            queue.submit("lane-b", task),
        )
        elapsed = time.monotonic() - start

        assert max_running >= 2 or elapsed < 0.09

    asyncio.run(run_test())
