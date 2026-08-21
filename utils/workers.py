"""
Concurrency utilities for the research pipeline.

Provides a :class:`WorkerPool` that bundles a ``ThreadPoolExecutor`` with
an ``asyncio.Semaphore`` and a **singleton global rate limiter** so that
concurrent research passes across the whole agent share a single request
budget. This prevents bans and keeps RAM/CPU bounded on a 16 GB system.
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, Callable, Coroutine, TypeVar

T = TypeVar("T")


class _GlobalRateLimiter:
    """Process-wide singleton rate limiter.

    Ensures at least ``rate_limit_delay`` seconds pass between successive
    outgoing requests, regardless of how many :class:`WorkerPool` instances
    are active.
    """

    _instance: _GlobalRateLimiter | None = None
    _lock = Lock()

    def __init__(self, rate_limit_delay: float = 1.0) -> None:
        self.rate_limit_delay = rate_limit_delay
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls, rate_limit_delay: float = 1.0) -> _GlobalRateLimiter:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(rate_limit_delay)
        return cls._instance

    async def wait_if_needed(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._last_request + self.rate_limit_delay - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


def get_global_rate_limiter(rate_limit_delay: float = 1.0) -> _GlobalRateLimiter:
    """Return the process-wide rate limiter singleton."""
    return _GlobalRateLimiter.get(rate_limit_delay)


class WorkerPool:
    """Concurrency pool with local semaphore + global rate limiting.

    Args:
        max_workers: Maximum concurrent threads for sync work.
        rate_limit_delay: Minimum seconds between requests globally.
    """

    def __init__(
        self,
        max_workers: int = 4,
        rate_limit_delay: float = 1.0,
    ) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.semaphore = asyncio.Semaphore(max_workers)
        self.rate_limiter = get_global_rate_limiter(rate_limit_delay)

    @asynccontextmanager
    async def throttle(self):
        """Acquire both the local semaphore and the global rate limit."""
        async with self.semaphore:
            await self.rate_limiter.wait_if_needed()
            yield

    async def run_sync(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a synchronous *func* in the thread pool under rate limiting."""
        async with self.throttle():
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.executor, func, *args, **kwargs)

    async def gather(
        self,
        coros: list[Coroutine[Any, Any, T]],
        *,
        return_exceptions: bool = False,
    ) -> list[T | BaseException]:
        """Run multiple coroutines concurrently, respecting rate limits.

        Each coroutine is responsible for calling :meth:`throttle` before
        issuing its own request. This method just wraps ``asyncio.gather``
        with sensible defaults for research workloads.
        """
        return list(
            await asyncio.gather(*coros, return_exceptions=return_exceptions)
        )

    def shutdown(self, wait: bool = True) -> None:
        """Tear down the underlying executor."""
        self.executor.shutdown(wait=wait)
