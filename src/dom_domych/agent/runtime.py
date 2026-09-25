"""Локальный runtime: только разрешённые типизированные tools и проверенный контекст."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import ValidationError

from dom_domych.agent.contracts import StrictModel, TrustedContext
from dom_domych.agent.llm import LlmPort


class AgentMode(StrEnum):
    TRIAGE = "triage"
    PROBLEM = "problem"
    INITIATIVE = "initiative"
    FOLLOWUP = "followup"


class ToolExecution(StrictModel):
    ok: bool
    data: dict[str, str | int | bool | None] | None = None
    error_code: str | None = None
    entity_version: int | None = None
    source_refs: tuple[str, ...] = ()


ToolHandler = Callable[[StrictModel, TrustedContext], Awaitable[ToolExecution]]


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
        self.llm = llm
        self.definitions = {definition.name: definition for definition in definitions}
        self.max_calls = max_calls

    async def run(
        self, messages: Sequence[dict[str, str]], context: TrustedContext, mode: AgentMode
    ) -> RunOutcome:
        conversation = list(messages)
        audit: list[ToolAudit] = []
        available = [
            definition
            for definition in self.definitions.values()
            if mode in definition.modes
            and (definition.capability is None or definition.capability in context.capabilities)
        ]
        schemas: list[dict[str, object]] = [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.input_model.model_json_schema(),
            }
            for definition in available
        ]
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
            for call in response.tool_calls:
                if used_calls >= self.max_calls:
                    return RunOutcome("budget_exhausted", "", tuple(audit))
                used_calls += 1
                definition = self.definitions.get(call.name)
                if definition is None or definition not in available:
                    result = ToolExecution(ok=False, error_code="FORBIDDEN_TOOL")
                else:
                    try:
                        args = definition.input_model.model_validate_json(call.arguments_json)
                    except ValidationError:
                        result = ToolExecution(ok=False, error_code="VALIDATION_ERROR")
                    else:
                        result = await definition.handler(args, context)
                had_tool_error = had_tool_error or not result.ok
                audit.append(
                    ToolAudit(
                        name=call.name,
                        outcome="ok" if result.ok else (result.error_code or "TOOL_ERROR"),
                        entity_version=result.entity_version,
                        source_refs=result.source_refs,
                    )
                )
                conversation.append(
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {"name": call.name, **result.model_dump()}, default=str
                        ),
                    }
                )
