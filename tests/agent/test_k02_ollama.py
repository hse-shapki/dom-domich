from __future__ import annotations

import json

import httpx
import pytest

from dom_domych.infrastructure.llm.ollama import OllamaPort


@pytest.mark.asyncio
async def test_ollama_native_tool_calls_are_typed_and_deduplicated() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        call = {
            "id": "call_1",
            "function": {"name": "case.search", "arguments": {"query": "темно"}},
        }
        return httpx.Response(
            200,
            json={"message": {"content": "рассуждение", "tool_calls": [call, call]}},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://127.0.0.1:11434"
    ) as client:
        result = await OllamaPort(client, "fixture-model").complete(
            [{"role": "user", "content": "Темно"}],
            [
                {
                    "name": "case.search",
                    "description": "Поиск",
                    "parameters": {"type": "object"},
                }
            ],
        )

    assert captured[0]["think"] is False
    assert captured[0]["options"] == {"num_predict": 512, "temperature": 0}
    assert captured[0]["messages"][0]["role"] == "system"
    assert result.text == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "case.search"
    assert result.tool_calls[0].arguments_json == '{"query":"темно"}'


@pytest.mark.asyncio
async def test_ollama_returns_text_when_no_tool_is_called() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": {"content": "Уточните этаж"}})
        ),
        base_url="http://127.0.0.1:11434",
    ) as client:
        result = await OllamaPort(client, "fixture-model").complete([], [])

    assert result.text == "Уточните этаж"
    assert not result.tool_calls


@pytest.mark.asyncio
async def test_ollama_converts_tool_history_to_native_messages() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "Готово"}})

    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "case.search",
                        "arguments": '{"query":"темно"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://127.0.0.1:11434"
    ) as client:
        await OllamaPort(client, "fixture-model").complete(history, [])

    assert captured[0]["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "case.search", "arguments": {"query": "темно"}}}],
        },
        {"role": "tool", "content": '{"ok":true}', "tool_name": "case.search"},
    ]


@pytest.mark.asyncio
async def test_ollama_requests_final_text_after_successful_write() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "Дело создано"}})

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "case.create", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
    ]
    tools = [
        {
            "name": "case.create",
            "description": "Создание",
            "parameters": {"type": "object"},
            "effect": "write",
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://127.0.0.1:11434"
    ) as client:
        await OllamaPort(client, "fixture-model").complete(messages, tools)

    instruction = captured[0]["messages"][0]["content"]
    assert "не вызывай tool повторно" in instruction
