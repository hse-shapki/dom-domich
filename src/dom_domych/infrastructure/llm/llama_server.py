"""Клиент документированного OpenAI-compatible chat API llama-server."""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dom_domych.agent.llm import LlmResponse, LlmToolCall


class _Function(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    name: str
    arguments: str


class _ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: str
    function: _Function


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    content: str | None = None
    tool_calls: list[_ToolCall] = Field(default_factory=list)


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    message: _Message


class _Completion(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    choices: list[_Choice]


class LlamaServerPort:
    """Использует общий AsyncClient; не создаёт сетевой клиент на каждый вызов."""

    def __init__(self, client: httpx.AsyncClient, model: str, *, max_tokens: int = 512) -> None:
        if not model or max_tokens < 1:
            raise ValueError("Неверная конфигурация inference")
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    async def complete(
        self, messages: Sequence[dict[str, object]], tools: Sequence[dict[str, object]]
    ) -> LlmResponse:
        functions = [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["parameters"],
                },
            }
            for item in tools
        ]
        body: dict[str, object] = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if functions:
            body["tools"] = functions
            body["tool_choice"] = "auto"
        try:
            response = await self.client.post("/v1/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise TimeoutError("Inference timeout") from exc
        except httpx.ConnectError as exc:
            raise ConnectionError("Inference connection failed") from exc
        if response.status_code in (429, 502, 503, 504):
            raise ConnectionError(f"Inference temporarily unavailable: {response.status_code}")
        response.raise_for_status()
        try:
            completion = _Completion.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise ValueError("Неверный ответ inference") from exc
        if not completion.choices:
            raise ValueError("Inference вернул пустой список choices")
        message = completion.choices[0].message
        return LlmResponse(
            text=message.content or "",
            tool_calls=tuple(
                LlmToolCall(
                    name=call.function.name,
                    arguments_json=call.function.arguments,
                    call_id=call.id,
                )
                for call in message.tool_calls
            ),
        )
