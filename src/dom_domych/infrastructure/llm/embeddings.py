"""HTTPX adapter для документированного llama-server embeddings API."""

from __future__ import annotations

import math

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _EmbeddingItem(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    embedding: list[float]


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    data: list[_EmbeddingItem] = Field(min_length=1)


class LlamaServerEmbeddings:
    """Разделяет AsyncClient с lifespan; размерность фиксирована для индекса pgvector."""

    def __init__(self, client: httpx.AsyncClient, model: str, revision: str) -> None:
        self.client = client
        self.model = model
        self.revision = revision

    async def embed(self, text: str) -> tuple[float, ...]:
        if not text.strip():
            raise ValueError("Пустой embedding input")
        try:
            response = await self.client.post(
                "/v1/embeddings",
                json={"model": self.model, "input": text, "encoding_format": "float"},
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError("Embedding timeout") from exc
        except httpx.ConnectError as exc:
            raise ConnectionError("Embedding connection failed") from exc
        response.raise_for_status()
        try:
            data = _EmbeddingResponse.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise ValueError("Неверный embedding response") from exc
        vector = tuple(data.data[0].embedding)
        if len(vector) != 1024 or not all(math.isfinite(item) for item in vector):
            raise ValueError("Некорректная размерность или значение embedding")
        return vector
