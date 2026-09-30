"""Нативный Ollama chat adapter для локальных моделей с tool calls."""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dom_domych.agent.llm import LlmResponse, LlmToolCall


class _OllamaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Function(_OllamaModel):
    name: str
    arguments: dict[str, object] | str


class _ToolCall(_OllamaModel):
    id: str | None = None
    function: _Function


class _Message(_OllamaModel):
    content: str = ""
    tool_calls: list[_ToolCall] = Field(default_factory=list)


class _Completion(_OllamaModel):
    message: _Message


class OllamaPort:
    """Вызывает `/api/chat`; одинаковые tool calls одной генерации выполняются один раз."""

    def __init__(self, client: httpx.AsyncClient, model: str, *, max_tokens: int = 512) -> None:
        if not model or max_tokens < 1:
            raise ValueError("Неверная конфигурация Ollama inference")
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
        request_messages = self._messages(messages)
        if functions:
            completed_write = self._completed_write(messages, tools)
            request_messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Предыдущее изменяющее действие успешно. Кратко сообщи его результат "
                        "пользователю и не вызывай tool повторно."
                        if completed_write
                        else "Ты обязан сразу вызвать один из предоставленных tools для "
                        "следующего действия. Не рассуждай и не пиши объяснение до результата tool."
                    ),
                },
            )
        body: dict[str, object] = {
            "model": self.model,
            "messages": request_messages,
            "stream": False,
            "think": False,
            "options": {"num_predict": self.max_tokens, "temperature": 0},
        }
        if functions:
            body["tools"] = functions
        try:
            response = await self.client.post("/api/chat", json=body)
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
            raise ValueError("Неверный ответ Ollama inference") from exc

        calls: list[LlmToolCall] = []
        seen: set[tuple[str, str]] = set()
        for index, call in enumerate(completion.message.tool_calls, 1):
            arguments = (
                call.function.arguments
                if isinstance(call.function.arguments, str)
                else json.dumps(call.function.arguments, ensure_ascii=False, separators=(",", ":"))
            )
            key = (call.function.name, arguments)
            if key in seen:
                continue
            seen.add(key)
            calls.append(
                LlmToolCall(
                    name=call.function.name,
                    arguments_json=arguments,
                    call_id=call.id or f"ollama_call_{index}",
                )
            )
        return LlmResponse(completion.message.content if not calls else "", tuple(calls))

    @staticmethod
    def _completed_write(
        messages: Sequence[dict[str, object]], tools: Sequence[dict[str, object]]
    ) -> bool:
        effects = {
            item.get("name"): item.get("effect")
            for item in tools
            if isinstance(item.get("name"), str)
        }
        calls: dict[str, str] = {}
        for message in messages:
            raw_calls = message.get("tool_calls")
            if message.get("role") == "assistant" and isinstance(raw_calls, list):
                for raw_call in raw_calls:
                    if not isinstance(raw_call, dict):
                        continue
                    function = raw_call.get("function")
                    call_id = raw_call.get("id")
                    if (
                        isinstance(function, dict)
                        and isinstance(function.get("name"), str)
                        and isinstance(call_id, str)
                    ):
                        calls[call_id] = function["name"]
            if message.get("role") != "tool":
                continue
            call_id = message.get("tool_call_id")
            name = calls.get(call_id) if isinstance(call_id, str) else None
            if effects.get(name) not in {"write", "external"}:
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                continue
            if isinstance(result, dict) and result.get("ok") is True:
                return True
        return False

    @staticmethod
    def _messages(messages: Sequence[dict[str, object]]) -> list[dict[str, object]]:
        """Переводит сохранённую OpenAI-style историю в нативный формат Ollama."""

        converted: list[dict[str, object]] = []
        call_names: dict[str, str] = {}
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            raw_calls = message.get("tool_calls")
            if role == "assistant" and isinstance(raw_calls, list):
                native_calls: list[dict[str, object]] = []
                for raw_call in raw_calls:
                    if not isinstance(raw_call, dict):
                        continue
                    function = raw_call.get("function")
                    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                        continue
                    name = function["name"]
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                    if not isinstance(arguments, dict):
                        arguments = {}
                    call_id = raw_call.get("id")
                    if isinstance(call_id, str):
                        call_names[call_id] = name
                    native_calls.append({"function": {"name": name, "arguments": arguments}})
                converted.append(
                    {"role": "assistant", "content": content, "tool_calls": native_calls}
                )
                continue
            if role == "tool":
                call_id = message.get("tool_call_id")
                tool_name = call_names.get(call_id) if isinstance(call_id, str) else None
                native_tool: dict[str, object] = {"role": "tool", "content": content}
                if tool_name is not None:
                    native_tool["tool_name"] = tool_name
                converted.append(native_tool)
                continue
            converted.append({"role": role, "content": content})
        return converted
