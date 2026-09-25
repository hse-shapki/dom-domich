from __future__ import annotations

from uuid import uuid4

import pytest

from dom_domych.agent.contracts import CaseSearch, StrictModel, TrustedContext
from dom_domych.agent.llm import FakeLlmPort, LlmResponse, LlmToolCall
from dom_domych.agent.runtime import (
    AgentMode,
    AgentRuntime,
    ToolDefinition,
    ToolExecution,
)


def _context(capabilities: frozenset[str] = frozenset()) -> TrustedContext:
    return TrustedContext(
        house_id=uuid4(),
        actor_id=uuid4(),
        event_id=uuid4(),
        run_id=uuid4(),
        capabilities=capabilities,
    )


@pytest.mark.asyncio
async def test_valid_tool_chain_receives_trusted_house_and_audits_result() -> None:
    context = _context(frozenset({"case.read"}))
    seen: list[tuple[StrictModel, TrustedContext]] = []

    async def handler(args: StrictModel, trusted: TrustedContext) -> ToolExecution:
        seen.append((args, trusted))
        return ToolExecution(
            ok=True,
            data={"case_id": "fixture"},
            entity_version=2,
            source_refs=("message:fixture",),
        )

    fake = FakeLlmPort(
        [
            LlmResponse("", (LlmToolCall("case.search", '{"query":"темно на лестнице"}'),)),
            LlmResponse("Найдено похожее дело"),
        ]
    )
    runtime = AgentRuntime(
        fake,
        [
            ToolDefinition(
                name="case.search",
                description="Ищет дела",
                input_model=CaseSearch,
                modes=frozenset({AgentMode.TRIAGE}),
                effect="read",
                capability="case.read",
                handler=handler,
            )
        ],
    )
    result = await runtime.run([{"role": "user", "content": "Темно"}], context, AgentMode.TRIAGE)
    assert result.status == "completed"
    assert result.audit[0].outcome == "ok"
    assert result.audit[0].source_refs == ("message:fixture",)
    assert len(seen) == 1
    assert seen[0][1].house_id == context.house_id
    assert fake.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        '{"query":"темно","house_id":"00000000-0000-0000-0000-000000000000"}',
        '{"query":9}',
    ],
)
async def test_invalid_arguments_never_reach_handler(arguments: str) -> None:
    async def handler(args: StrictModel, trusted: TrustedContext) -> ToolExecution:
        raise AssertionError("Handler не должен вызываться")

    fake = FakeLlmPort(
        [
            LlmResponse("", (LlmToolCall("case.search", arguments),)),
            LlmResponse("Я всё сделал"),
        ]
    )
    runtime = AgentRuntime(
        fake,
        [
            ToolDefinition(
                "case.search",
                "Ищет",
                CaseSearch,
                frozenset({AgentMode.TRIAGE}),
                "read",
                None,
                handler,
            )
        ],
    )
    result = await runtime.run([], _context(), AgentMode.TRIAGE)
    assert result.status == "failed"
    assert result.text == ""
    assert result.audit[0].outcome == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_unknown_or_unavailable_tool_is_blocked() -> None:
    fake = FakeLlmPort(
        [
            LlmResponse("", (LlmToolCall("shell.exec", "{}"),)),
            LlmResponse("Готово"),
        ]
    )
    result = await AgentRuntime(fake, []).run([], _context(), AgentMode.PROBLEM)
    assert result.status == "failed"
    assert result.audit[0].outcome == "FORBIDDEN_TOOL"


@pytest.mark.asyncio
async def test_tool_budget_stops_repeated_calls() -> None:
    fake = FakeLlmPort(
        [
            LlmResponse("", (LlmToolCall("shell.exec", "{}"),)),
            LlmResponse("", (LlmToolCall("shell.exec", "{}"),)),
        ]
    )
    result = await AgentRuntime(fake, [], max_calls=1).run([], _context(), AgentMode.TRIAGE)
    assert result.status == "budget_exhausted"
    assert len(result.audit) == 1
