"""Embedding API проверяется MockTransport, без запуска модели на рабочем Mac."""

import httpx
import pytest

from dom_domych.infrastructure.llm.embeddings import LlamaServerEmbeddings


@pytest.mark.asyncio
async def test_embedding_adapter_uses_documented_api_and_checks_dimension() -> None:
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        seen.append(request.read().decode())
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1024}]})

    async with httpx.AsyncClient(
        base_url="http://inference.local", transport=httpx.MockTransport(respond)
    ) as client:
        vector = await LlamaServerEmbeddings(client, "Qwen3-Embedding-0.6B", "rev").embed(
            "освещение лестницы"
        )
    assert len(vector) == 1024
    assert '"encoding_format":"float"' in seen[0]


@pytest.mark.asyncio
async def test_embedding_adapter_rejects_wrong_dimension() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    async with httpx.AsyncClient(
        base_url="http://inference.local", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(ValueError):
            await LlamaServerEmbeddings(client, "model", "rev").embed("текст")
