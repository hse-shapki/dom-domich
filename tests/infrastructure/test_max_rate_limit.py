"""A11: лимиты MAX применяются до исходящего запроса."""

import pytest

from dom_domych.infrastructure.max.rate_limit import AsyncIntervalLimiter


@pytest.mark.asyncio
async def test_interval_limiter_waits_between_calls() -> None:
    current = 10.0
    delays: list[float] = []

    def now() -> float:
        return current

    async def sleep(delay: float) -> None:
        nonlocal current
        delays.append(delay)
        current += delay

    limiter = AsyncIntervalLimiter(2, now=now, sleep=sleep)

    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    assert delays == [0.5, 0.5]
