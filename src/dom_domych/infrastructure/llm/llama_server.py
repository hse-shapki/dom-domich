"""Клиент документированного OpenAI-compatible chat API llama-server."""

from __future__ import annotations

import json
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
        request_messages = list(messages)
        if functions:
            request_messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Для действий используй только предоставленные tools и не объявляй "
                        "успех до результата tool. Если transport модели не формирует "
                        "tool_calls, при вызове верни только JSON "
                        '{"name":"имя tool","arguments":{...}} без Markdown.'
                    ),
                },
            )
        body: dict[str, object] = {
            "model": self.model,
            "messages": request_messages,
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
        tool_calls = tuple(
            LlmToolCall(
                name=call.function.name,
                arguments_json=call.function.arguments,
                call_id=call.id,
            )
            for call in message.tool_calls
        )
        if not tool_calls and message.content and tools:
            tool_calls = self._compat_tool_call(message.content, tools)
        return LlmResponse(
            text="" if tool_calls else message.content or "",
            tool_calls=tool_calls,
        )

    @staticmethod
    def _compat_tool_call(
        content: str, tools: Sequence[dict[str, object]]
    ) -> tuple[LlmToolCall, ...]:
        """Принимает только точный allowlisted JSON от моделей без tool-call шаблона."""

        stripped = content.strip()
        if stripped.startswith("```json\n") and stripped.endswith("\n```"):
            stripped = stripped.removeprefix("```json\n").removesuffix("\n```")
        try:
            candidate = json.loads(stripped)
        except (TypeError, ValueError):
            return ()
        if not isinstance(candidate, dict) or set(candidate) != {"name", "arguments"}:
            return ()
        name = candidate.get("name")
        arguments = candidate.get("arguments")
        allowed = {tool.get("name") for tool in tools if isinstance(tool.get("name"), str)}
        if not isinstance(name, str) or name not in allowed or not isinstance(arguments, dict):
            return ()
        return (
            LlmToolCall(
                name=name,
                arguments_json=json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
                call_id="compat_call_1",
            ),
        )
