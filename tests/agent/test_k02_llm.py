from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from dom_domych.agent.llm import FakeLlmPort, LlmResponse, RetryingLlmPort


@pytest.mark.asyncio
async def test_fake_llm_returns_fixture_without_network() -> None:
    fake = FakeLlmPort([LlmResponse(text="Нужно уточнить подъезд")])
    response = await RetryingLlmPort(fake).complete([{"role": "user", "content": "Темно"}], [])
    assert response.text == "Нужно уточнить подъезд"
    assert fake.call_count == 1


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_not_reported_as_success() -> None:
    class SlowPort:
        calls = 0

        async def complete(
            self, messages: Sequence[dict[str, str]], tools: Sequence[dict[str, object]]
        ) -> LlmResponse:
            self.calls += 1
            await asyncio.sleep(0.1)
            return LlmResponse(text="Поздний ответ")

    slow = SlowPort()
    with pytest.raises(TimeoutError):
        await RetryingLlmPort(slow, timeout_seconds=0.001, attempts=2).complete([], [])
    assert slow.calls == 2


@pytest.mark.asyncio
async def test_validation_failure_is_not_retried() -> None:
    class BrokenPort:
        calls = 0

        async def complete(
            self, messages: Sequence[dict[str, str]], tools: Sequence[dict[str, object]]
        ) -> LlmResponse:
            self.calls += 1
            raise ValueError("Неверный ответ модели")

    broken = BrokenPort()
    with pytest.raises(ValueError):
        await RetryingLlmPort(broken, attempts=3).complete([], [])
    assert broken.calls == 1
