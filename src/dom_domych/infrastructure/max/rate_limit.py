"""Ограничители исходящих вызовов MAX внутри одного process consumer."""

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

Sleep = Callable[[float], Awaitable[None]]
Monotonic = Callable[[], float]


class AsyncIntervalLimiter:
    """Сериализует вызовы так, чтобы между ними прошёл заданный интервал."""

    def __init__(
        self,
        rate_per_second: float,
        *,
        now: Monotonic = monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._interval = 1 / rate_per_second
        self._now = now
        self._sleep = sleep
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            current = self._now()
            delay = max(0.0, self._next_at - current)
            if delay:
                await self._sleep(delay)
                current = self._now()
            self._next_at = max(current, self._next_at) + self._interval


class MaxRateLimits:
    """Общий, callback и per-dialog лимиты для одного MAX access token."""

    def __init__(
        self,
        *,
        global_rps: float = 30,
        dialog_rps: float = 2,
    ) -> None:
        self._global = AsyncIntervalLimiter(global_rps)
        self._dialog_rps = dialog_rps
        self._dialogs: dict[str, AsyncIntervalLimiter] = {}
        self._dialogs_lock = asyncio.Lock()

    async def acquire(self, operation: str, dialog_key: str | None = None) -> None:
        await self._global.acquire()
        if dialog_key is not None:
            bucket_key = f"{operation}:{dialog_key}"
            async with self._dialogs_lock:
                limiter = self._dialogs.setdefault(
                    bucket_key, AsyncIntervalLimiter(self._dialog_rps)
                )
            await limiter.acquire()
