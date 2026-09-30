"""Локальный runtime: только разрешённые типизированные tools и проверенный контекст."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

import structlog
from pydantic import ValidationError

from dom_domych.agent.contracts import StrictModel, TrustedContext
from dom_domych.agent.llm import LlmPort
from dom_domych.contracts.errors import ContractError, ErrorCode
from dom_domych.contracts.tools import ToolResult

logger = structlog.get_logger()

_TRUSTED_TOOL_FIELDS = {
    "case.create": frozenset({"source_message_id", "operation_id"}),
    "case.attach_message": frozenset({"message_id", "operation_id"}),
    "request.prepare": frozenset({"operation_id"}),
    "request.submit": frozenset({"operation_id"}),
}


class AgentMode(StrEnum):
    TRIAGE = "triage"
    PROBLEM = "problem"
    INITIATIVE = "initiative"
    FOLLOWUP = "followup"


ToolHandler = Callable[[StrictModel, TrustedContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[StrictModel]
    modes: frozenset[AgentMode]
    effect: Literal["read", "write", "external"]
    capability: str | None
    handler: ToolHandler


@dataclass(frozen=True, slots=True)
class ToolAudit:
    name: str
    outcome: str
    entity_version: int | None
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunOutcome:
    status: Literal["completed", "failed", "budget_exhausted"]
    text: str
    audit: tuple[ToolAudit, ...]


class AgentRuntime:
    """Валидирует каждый model call до handler; ошибку handler не выдаёт за успех."""

    def __init__(
        self, llm: LlmPort, definitions: Sequence[ToolDefinition], *, max_calls: int = 6
    ) -> None:
        if max_calls < 1 or max_calls > 20:
            raise ValueError("Некорректный лимит вызовов")
        names = [definition.name for definition in definitions]
        if len(names) != len(set(names)):
            raise ValueError("Tool name должен быть уникальным")
        for definition in definitions:
            if {
                "house_id",
                "actor_id",
                "capabilities",
            } & definition.input_model.model_fields.keys():
                raise ValueError("Tool schema содержит доверенные поля")
            if definition.effect != "read" and definition.capability is None:
                raise ValueError("Запись требует capability")
        self.llm = llm
        self.definitions = {definition.name: definition for definition in definitions}
        self.max_calls = max_calls

    async def run(
        self, messages: Sequence[dict[str, object]], context: TrustedContext, mode: AgentMode
    ) -> RunOutcome:
        conversation = list(messages)
        audit: list[ToolAudit] = []
        available = [
            definition
            for definition in self.definitions.values()
            if mode in definition.modes
            and (definition.capability is None or definition.capability in context.capabilities)
        ]
        schemas: list[dict[str, object]] = []
        for schema_definition in available:
            parameters = schema_definition.input_model.model_json_schema()
            trusted_fields = _TRUSTED_TOOL_FIELDS.get(schema_definition.name, frozenset())
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                for field in trusted_fields:
                    properties.pop(field, None)
            required = parameters.get("required")
            if isinstance(required, list):
                parameters["required"] = [
                    field for field in required if field not in trusted_fields
                ]
            schemas.append(
                {
                    "name": schema_definition.name,
                    "description": schema_definition.description,
                    "parameters": parameters,
                    "effect": schema_definition.effect,
                }
            )
        used_calls = 0
        had_tool_error = False
        while True:
            try:
                response = await self.llm.complete(conversation, schemas)
            except (TimeoutError, ConnectionError, ValueError, RuntimeError):
                return RunOutcome("failed", "", tuple(audit))
            if not response.tool_calls:
                return RunOutcome(
                    "failed" if had_tool_error else "completed",
                    "" if had_tool_error else response.text,
                    tuple(audit),
                )
            assistant_calls = [
                {
                    "id": call.call_id or f"call_{used_calls + index + 1}",
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments_json},
                }
                for index, call in enumerate(response.tool_calls)
            ]
            conversation.append(
                {
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": assistant_calls,
                }
            )
            for call, assistant_call in zip(response.tool_calls, assistant_calls, strict=True):
                if used_calls >= self.max_calls:
                    return RunOutcome("budget_exhausted", "", tuple(audit))
                used_calls += 1
                definition = self.definitions.get(call.name)
                if definition is None or definition not in available:
                    result = ToolResult(ok=False, error=ContractError(code=ErrorCode.FORBIDDEN))
                else:
                    try:
                        raw_arguments = json.loads(call.arguments_json)
                        if not isinstance(raw_arguments, dict):
                            raise ValueError("tool arguments must be an object")
                        trusted_fields = _TRUSTED_TOOL_FIELDS.get(call.name, frozenset())
                        for field in trusted_fields:
                            raw_arguments.pop(field, None)
                        if "source_message_id" in trusted_fields:
                            raw_arguments["source_message_id"] = str(context.event_id)
                        if "message_id" in trusted_fields:
                            raw_arguments["message_id"] = str(context.event_id)
                        if "operation_id" in trusted_fields:
                            raw_arguments["operation_id"] = str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"dom-domich:{context.run_id}:{used_calls}:{call.name}",
                                )
                            )
                        args = definition.input_model.model_validate_json(json.dumps(raw_arguments))
                    except (json.JSONDecodeError, ValidationError, ValueError):
                        result = ToolResult(
                            ok=False, error=ContractError(code=ErrorCode.VALIDATION_ERROR)
                        )
                    else:
                        try:
                            result = ToolResult.model_validate(
                                await definition.handler(args, context)
                            )
                        except Exception as exc:
                            logger.error(
                                "agent_tool_failed",
                                name=call.name,
                                run_id=str(context.run_id),
                                error=type(exc).__name__,
                            )
                            audit.append(ToolAudit(call.name, "HANDLER_ERROR", None, ()))
                            return RunOutcome("failed", "", tuple(audit))
                had_tool_error = had_tool_error or not result.ok
                outcome_code = "ok"
                if not result.ok:
                    assert result.error is not None
                    outcome_code = result.error.code.value
                audit.append(
                    ToolAudit(
                        name=call.name,
                        outcome=outcome_code,
                        entity_version=result.entity_version,
                        source_refs=result.source_refs,
                    )
                )
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": assistant_call["id"],
                        "content": json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                    }
                )
