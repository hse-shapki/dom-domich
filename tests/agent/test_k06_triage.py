"""K06: несколько тем, срочность и источниковые ответы без живой модели."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dom_domych.agent.contracts import KnowledgeHit, KnowledgeSearch, TrustedContext
from dom_domych.agent.llm import FakeLlmPort, LlmResponse
from dom_domych.agent.triage import (
    LlmTriagePort,
    MessageKind,
    TriageDecision,
    TriageItem,
    TriageService,
)
from dom_domych.contracts.base import ExecutionMode, PrincipalType


def _context() -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=uuid4(),
        actor_id=uuid4(),
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset({"knowledge.read"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


class FakeKnowledge:
    def __init__(self, hits: tuple[KnowledgeHit, ...] = ()) -> None:
        self.hits = hits
        self.queries: list[str] = []

    async def search(
        self, command: KnowledgeSearch, context: TrustedContext, *, at: datetime
    ) -> tuple[KnowledgeHit, ...]:
        self.queries.append(command.query)
        return self.hits


@pytest.mark.asyncio
async def test_llm_triage_validates_json_and_rejects_tools() -> None:
    llm = FakeLlmPort(
        [
            LlmResponse(
                '{"items":[{"kind":"problem","text":"Не горит лампа",'
                '"entrance":2,"object_name":"лампа"}]}'
            )
        ]
    )
    result = await LlmTriagePort(llm).classify("В подъезде не горит лампа")
    assert result.items[0].entrance == 2
    with pytest.raises(ValueError):
        await LlmTriagePort(FakeLlmPort([LlmResponse("не JSON")])).classify("Текст")


@pytest.mark.asyncio
async def test_multiple_problems_are_separate_routes_and_gas_is_urgent() -> None:
    decision = TriageDecision(
        items=(
            TriageItem(kind=MessageKind.PROBLEM, text="Не горит лампа", entrance=1),
            TriageItem(kind=MessageKind.PROBLEM, text="Не работает лифт", entrance=2),
        )
    )

    class Classifier:
        async def classify(self, message: str) -> TriageDecision:
            return decision

    routes = await TriageService(Classifier(), FakeKnowledge()).route(
        "Пахнет газом, и не горит лампа, и не работает лифт", _context(), at=datetime.now(UTC)
    )
    assert [route.kind for route in routes] == [
        MessageKind.EMERGENCY,
        MessageKind.PROBLEM,
        MessageKind.PROBLEM,
    ]
    assert routes[1].entrance == 1 and routes[2].entrance == 2


@pytest.mark.asyncio
async def test_question_needs_reviewed_source_and_conversation_does_not_create_case() -> None:
    class Classifier:
        async def classify(self, message: str) -> TriageDecision:
            kind = MessageKind.QUESTION if "Кто" in message else MessageKind.CONVERSATION
            return TriageDecision(items=(TriageItem(kind=kind, text=message),))

    now = datetime.now(UTC)
    knowledge = FakeKnowledge()
    service = TriageService(Classifier(), knowledge)
    question = await service.route("Кто отвечает за свет?", _context(), at=now)
    assert question[0].next_action == "ask_clarification" and question[0].answer is None
    assert knowledge.queries == ["Кто отвечает за свет?"]
    source_id = uuid4()
    knowledge.hits = (
        KnowledgeHit(source_id=source_id, revision=2, excerpt="Источник", reviewed=False),
    )
    assert (await service.route("Кто отвечает за свет?", _context(), at=now))[0].answer is None
    knowledge.hits = (
        KnowledgeHit(source_id=source_id, revision=2, excerpt="Источник", reviewed=True),
    )
    answered = await service.route("Кто отвечает за свет?", _context(), at=now)
    assert answered[0].source_refs == (f"{source_id}:2",)
    conversation = await service.route("Привет всем", _context(), at=now)
    assert conversation[0].next_action == "none"
