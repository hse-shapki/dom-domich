from uuid import uuid4

import pytest

from dom_domych.agent.contracts import CaseSearch
from dom_domych.agent.fakes import FakeCasePort, FakeKnowledgePort, FakeRequestPort
from dom_domych.agent.llm import FakeLlmPort, LlmResponse, LlmToolCall
from dom_domych.agent.runtime import AgentMode, AgentRuntime
from dom_domych.agent.tool_handlers import KToolHandlers
from dom_domych.agent.tools import build_k_tool_definitions
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext


def _context(capabilities: frozenset[str]) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=uuid4(),
        actor_id=uuid4(),
        principal_type=PrincipalType.RESIDENT,
        capabilities=capabilities,
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


def test_registry_covers_published_k_schemas_once() -> None:
    cases = FakeCasePort()
    definitions = build_k_tool_definitions(
        KToolHandlers(cases, FakeKnowledgePort(), FakeRequestPort(cases))
    )

    assert {definition.name for definition in definitions} == {
        "case.search",
        "case.get",
        "case.create",
        "case.attach_message",
        "knowledge.search",
        "request.prepare",
        "request.submit",
        "request.get_status",
    }
    assert len(definitions) == 8
    assert all(definition.input_model is not None for definition in definitions)
    assert next(item for item in definitions if item.name == "request.submit").effect == "external"


@pytest.mark.asyncio
async def test_registry_routes_validated_call_through_trusted_handler() -> None:
    cases = FakeCasePort()
    runtime = AgentRuntime(
        FakeLlmPort(
            [
                LlmResponse(
                    "",
                    (LlmToolCall("case.search", '{"query":"темно на лестнице"}'),),
                ),
                LlmResponse("Похожих дел нет"),
            ]
        ),
        build_k_tool_definitions(KToolHandlers(cases, FakeKnowledgePort(), FakeRequestPort(cases))),
    )

    result = await runtime.run(
        [{"role": "user", "content": "Темно"}],
        _context(frozenset({"case.read"})),
        AgentMode.TRIAGE,
    )

    assert result.status == "completed"
    assert result.audit[0].name == "case.search"
    assert result.audit[0].outcome == "ok"


def test_registry_does_not_publish_trusted_context_fields() -> None:
    cases = FakeCasePort()
    definitions = build_k_tool_definitions(
        KToolHandlers(cases, FakeKnowledgePort(), FakeRequestPort(cases))
    )

    search = next(item for item in definitions if item.name == "case.search")
    assert search.input_model is CaseSearch
    assert not {"house_id", "actor_id", "capabilities"} & search.input_model.model_fields.keys()
