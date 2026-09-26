from __future__ import annotations

import json

import httpx
import pytest

from dom_domych.agent.llm import RetryingLlmPort
from dom_domych.infrastructure.llm.llama_server import LlamaServerPort


@pytest.mark.asyncio
async def test_llama_server_tool_call_contract() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "case.search",
                                        "arguments": '{"query":"темно на лестнице"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://127.0.0.1:8080"
    ) as client:
        result = await LlamaServerPort(client, "fixture-model").complete(
            [{"role": "user", "content": "Темно на лестнице"}],
            [
                {
                    "name": "case.search",
                    "description": "Поиск дел",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                }
            ],
        )
    assert captured[0]["model"] == "fixture-model"
    assert captured[0]["tool_choice"] == "auto"
    assert result.tool_calls[0].call_id == "call_1"
    assert result.tool_calls[0].name == "case.search"


@pytest.mark.asyncio
async def test_llama_server_retries_transient_503_only_with_bound() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Уточните подъезд"}}]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://127.0.0.1:8080"
    ) as client:
        result = await RetryingLlmPort(
            LlamaServerPort(client, "fixture-model"), attempts=2
        ).complete([], [])
    assert calls == 2
    assert result.text == "Уточните подъезд"


@pytest.mark.asyncio
async def test_llama_server_rejects_malformed_success() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []})),
        base_url="http://127.0.0.1:8080",
    ) as client:
        with pytest.raises(ValueError, match="пустой"):
            await LlamaServerPort(client, "fixture-model").complete([], [])
