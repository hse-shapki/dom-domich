"""K13: события запускают fresh run и повтор не вызывает модель вновь."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from dom_domych.agent.continuation import AgentCoordinator, ContextBuilder, FakeRunStore
from dom_domych.agent.contracts import CaseCreate, CaseKind, TrustedContext
from dom_domych.agent.fakes import FakeCasePort
from dom_domych.agent.llm import FakeLlmPort, LlmResponse
from dom_domych.agent.runtime import AgentRuntime
from dom_domych.application.agent.events import EVENT_PROMPTS, AgentEventHandler
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource

NOW = datetime(2026, 9, 26, 13, tzinfo=UTC)


class FakeResolver:
    def __init__(self, case_id: UUID) -> None:
        self.case_id = case_id

    async def resolve(self, event: EventEnvelope) -> tuple[UUID, ExecutionMode]:
        return self.case_id, ExecutionMode.DEMO


class InspectingLlm(FakeLlmPort):
    def __init__(self) -> None:
        super().__init__([LlmResponse("Проверю следующий шаг") for _ in EVENT_PROMPTS])
        self.inputs: list[list[dict[str, object]]] = []

    async def complete(
        self, messages: list[dict[str, object]], tools: list[dict[str, object]]
    ) -> LlmResponse:
        self.inputs.append(list(messages))
        return await super().complete(messages, tools)


@pytest.mark.asyncio
async def test_all_continuations_read_fresh_case_and_retry_is_idempotent() -> None:
    house_id = uuid4()
    cases = FakeCasePort()
    case = await cases.create(
        CaseCreate(
            kind=CaseKind.PROBLEM,
            title="Нет света в подъезде",
            description="Темно на лестнице",
            source_message_id=uuid4(),
            operation_id=uuid4(),
        ),
        TrustedContext(
            run_id=uuid4(),
            event_id=uuid4(),
            house_id=house_id,
            actor_id=uuid4(),
            principal_type=PrincipalType.RESIDENT,
            capabilities=frozenset(),
            correlation_id=uuid4(),
            mode=ExecutionMode.DEMO,
        ),
    )
    llm = InspectingLlm()
    runs = FakeRunStore()
    handler = AgentEventHandler(
        FakeResolver(case.case_id),
        AgentCoordinator(ContextBuilder(cases, runs), AgentRuntime(llm, [])),
    )
    for index, name in enumerate(EVENT_PROMPTS, start=1):
        current = cases.cases[case.case_id][1]
        cases.cases[case.case_id] = (house_id, current.model_copy(update={"version": index + 1}))
        event = EventEnvelope(
            event_id=uuid4(),
            source=EventSource.DOMAIN,
            source_key=f"case:{index}",
            name=name,
            occurred_at=NOW,
            received_at=NOW,
            correlation_id=uuid4(),
            house_id=house_id,
            entity=EntityEventPayload(entity_id=case.case_id, entity_version=1),
        )
        assert await handler(event)
        assert f"версия {index + 1}" in str(llm.inputs[-1][0]["content"])
        if name is EventName.RESOLUTION_REJECTED:
            assert "Не удаляй прежние ответы" in str(llm.inputs[-1][1]["content"])
        assert await handler(event)
        assert llm.call_count == index
    assert len(runs.runs) == len(EVENT_PROMPTS)


@pytest.mark.asyncio
async def test_max_event_cannot_start_continuation() -> None:
    handler = AgentEventHandler(
        FakeResolver(uuid4()),
        AgentCoordinator(
            ContextBuilder(FakeCasePort(), FakeRunStore()),
            AgentRuntime(FakeLlmPort([]), []),
        ),
    )
    event = EventEnvelope(
        event_id=uuid4(),
        source=EventSource.MAX,
        source_key="max:1",
        name=EventName.RESOLUTION_REJECTED,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=uuid4(),
        house_id=uuid4(),
        entity=EntityEventPayload(entity_id=uuid4(), entity_version=1),
    )
    with pytest.raises(ValueError, match="UNTRUSTED_CONTINUATION_EVENT"):
        await handler(event)
