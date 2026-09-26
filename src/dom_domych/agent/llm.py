"""Порт inference и ограниченный retry для временного K02 fake пути."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LlmToolCall:
    name: str
    arguments_json: str
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    tool_calls: tuple[LlmToolCall, ...] = ()


class LlmPort(Protocol):
    """Модель получает только подготовленный контекст и JSON schemas."""

    async def complete(
        self, messages: Sequence[dict[str, object]], tools: Sequence[dict[str, object]]
    ) -> LlmResponse: ...


class RetryingLlmPort:
    """Ограничивает время попытки; повторяет только временный transport failure."""

    def __init__(self, inner: LlmPort, *, timeout_seconds: float = 30.0, attempts: int = 2) -> None:
        if timeout_seconds <= 0 or attempts < 1 or attempts > 3:
            raise ValueError("Некорректный бюджет inference")
        self.inner = inner
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts

    async def complete(
        self, messages: Sequence[dict[str, object]], tools: Sequence[dict[str, object]]
    ) -> LlmResponse:
        for attempt in range(self.attempts):
            try:
                return await asyncio.wait_for(
                    self.inner.complete(messages, tools), timeout=self.timeout_seconds
                )
            except (TimeoutError, ConnectionError):
                if attempt + 1 == self.attempts:
                    raise
        raise AssertionError("Недостижимая ветка")


class FakeLlmPort:
    """Возвращает заранее заданные ответы без сети и внешней модели."""

    def __init__(self, responses: Sequence[LlmResponse]) -> None:
        self.responses = deque(responses)
        self.call_count = 0

    async def complete(
        self, messages: Sequence[dict[str, object]], tools: Sequence[dict[str, object]]
    ) -> LlmResponse:
        self.call_count += 1
        if not self.responses:
            raise RuntimeError("Fake LLM: ответы исчерпаны")
        return self.responses.popleft()
