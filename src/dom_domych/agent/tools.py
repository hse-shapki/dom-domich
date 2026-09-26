"""Единый реестр K tools для локального agent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, cast

from dom_domych.agent.contracts import TOOL_INPUTS, StrictModel, TrustedContext
from dom_domych.agent.runtime import AgentMode, ToolDefinition
from dom_domych.agent.tool_handlers import KToolHandlers
from dom_domych.contracts.tools import ToolResult


def _handler(
    handlers: KToolHandlers, name: str
) -> Callable[[StrictModel, TrustedContext], Awaitable[ToolResult]]:
    async def execute(arguments: StrictModel, context: TrustedContext) -> ToolResult:
        return await handlers.execute(name, arguments.model_dump_json(), context)

    return execute


def build_k_tool_definitions(handlers: KToolHandlers) -> tuple[ToolDefinition, ...]:
    """Связывает опубликованные schemas с handlers без доверенных полей от модели."""

    specs = (
        (
            "case.search",
            "Найти похожие активные или недавно закрытые дела этого дома.",
            frozenset({AgentMode.TRIAGE, AgentMode.PROBLEM, AgentMode.INITIATIVE}),
            "read",
            "case.read",
        ),
        (
            "case.get",
            "Прочитать актуальную версию дела этого дома.",
            frozenset(AgentMode),
            "read",
            "case.read",
        ),
        (
            "case.create",
            "Создать новое дело после проверки кандидатов.",
            frozenset({AgentMode.TRIAGE, AgentMode.PROBLEM, AgentMode.INITIATIVE}),
            "write",
            "case.write",
        ),
        (
            "case.attach_message",
            "Привязать исходное сообщение к существующему делу с проверкой версии.",
            frozenset({AgentMode.TRIAGE, AgentMode.PROBLEM, AgentMode.INITIATIVE}),
            "write",
            "case.write",
        ),
        (
            "knowledge.search",
            "Найти проверенные источники и применимые правила.",
            frozenset(AgentMode),
            "read",
            "knowledge.read",
        ),
        (
            "request.prepare",
            "Подготовить версионированный черновик обращения по проверенному правилу.",
            frozenset({AgentMode.PROBLEM, AgentMode.FOLLOWUP}),
            "write",
            "request.write",
        ),
        (
            "request.submit",
            "Передать согласованную версию обращения demo-исполнителю.",
            frozenset({AgentMode.PROBLEM, AgentMode.FOLLOWUP}),
            "external",
            "request.submit",
        ),
        (
            "request.get_status",
            "Прочитать сохранённый статус обращения этого дома.",
            frozenset({AgentMode.PROBLEM, AgentMode.FOLLOWUP}),
            "read",
            "request.read",
        ),
        (
            "emergency.handle",
            "Без ожидания опроса подготовить срочное обращение или точное уточнение.",
            frozenset({AgentMode.TRIAGE, AgentMode.PROBLEM}),
            "write",
            "emergency.handle",
        ),
    )
    definitions: list[ToolDefinition] = []
    for name, description, modes, effect, capability in specs:
        definitions.append(
            ToolDefinition(
                name=name,
                description=description,
                input_model=TOOL_INPUTS[name],
                modes=modes,
                effect=cast(Literal["read", "write", "external"], effect),
                capability=capability,
                handler=_handler(handlers, name),
            )
        )
    return tuple(definitions)
