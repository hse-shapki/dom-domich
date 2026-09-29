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


@pytest.mark.asyncio
async def test_llama_server_accepts_exact_allowlisted_compat_tool_json() -> None:
    response = {
        "choices": [
            {"message": {"content": '{"name":"case.search","arguments":{"query":"темно"}}'}}
        ]
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
        base_url="http://127.0.0.1:8080",
    ) as client:
        result = await LlamaServerPort(client, "fixture-model").complete(
            [{"role": "user", "content": "Темно"}],
            [
                {
                    "name": "case.search",
                    "description": "Поиск",
                    "parameters": {"type": "object"},
                }
            ],
        )

    assert result.text == ""
    assert result.tool_calls[0].name == "case.search"
    assert result.tool_calls[0].arguments_json == '{"query":"темно"}'
    assert result.tool_calls[0].call_id == "compat_call_1"


@pytest.mark.asyncio
async def test_llama_server_accepts_single_json_fence_without_surrounding_text() -> None:
    content = '```json\n{"name":"case.search","arguments":{"query":"темно"}}\n```'
    response = {"choices": [{"message": {"content": content}}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
        base_url="http://127.0.0.1:8080",
    ) as client:
        result = await LlamaServerPort(client, "fixture-model").complete(
            [],
            [
                {
                    "name": "case.search",
                    "description": "Поиск",
                    "parameters": {"type": "object"},
                }
            ],
        )

    assert result.tool_calls[0].name == "case.search"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"name":"shell.exec","arguments":{}}',
        '{"name":"case.search","arguments":{},"extra":true}',
        'Вызову {"name":"case.search","arguments":{}}',
        'Текст\n```json\n{"name":"case.search","arguments":{}}\n```',
    ],
)
async def test_llama_server_does_not_execute_untrusted_compat_text(content: str) -> None:
    response = {"choices": [{"message": {"content": content}}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
        base_url="http://127.0.0.1:8080",
    ) as client:
        result = await LlamaServerPort(client, "fixture-model").complete(
            [],
            [
                {
                    "name": "case.search",
                    "description": "Поиск",
                    "parameters": {"type": "object"},
                }
            ],
        )

    assert not result.tool_calls
    assert result.text == content
