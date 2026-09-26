"""Порт вычисления embedding для проверенных источников."""

from typing import Protocol


class EmbeddingPort(Protocol):
    revision: str

    async def embed(self, text: str) -> tuple[float, ...]: ...
