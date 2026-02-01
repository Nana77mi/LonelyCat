import asyncio
import inspect
from typing import Awaitable, Callable, Dict, Tuple, TypeVar

T = TypeVar("T")


class LaneQueue:
    def __init__(self, max_concurrency: int = 4) -> None:
        self._lanes: Dict[str, asyncio.Queue[Tuple[Callable[[], Awaitable[T] | T], asyncio.Future[T]]]] = {}
        self._workers: Dict[str, asyncio.Task[None]] = {}
        self._state_lock = asyncio.Lock()
        self._global_semaphore = asyncio.Semaphore(max_concurrency)

    async def submit(self, lane_key: str, fn: Callable[[], Awaitable[T] | T]) -> T:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()

        async with self._state_lock:
            queue = self._lanes.get(lane_key)
            if queue is None:
                queue = asyncio.Queue()
                self._lanes[lane_key] = queue
                self._workers[lane_key] = asyncio.create_task(self._lane_worker(lane_key))

        await queue.put((fn, future))
        return await future

    async def _lane_worker(self, lane_key: str) -> None:
        queue = self._lanes[lane_key]
        while True:
            fn, future = await queue.get()
            try:
                async with self._global_semaphore:
                    result = fn()
                    if inspect.isawaitable(result):
                        result = await result
                if not future.cancelled():
                    future.set_result(result)
            except Exception as exc:
                if not future.cancelled():
                    future.set_exception(exc)
            finally:
                queue.task_done()
