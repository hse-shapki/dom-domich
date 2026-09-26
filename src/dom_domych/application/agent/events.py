"""K13: доверенные доменные события запускают новый run с текущим делом."""

from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.continuation import AgentCoordinator
from dom_domych.agent.runtime import AgentMode
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.jobs.scheduler import RevisionRouter
from dom_domych.application.requests.deadline import (
    RequestDeadlineHandler,
    RequestDeadlineRevisionReader,
)
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.request_models import RequestRow

EVENT_PROMPTS: dict[EventName, str] = {
    EventName.POLL_THRESHOLD_REACHED: (
        "Порог подтверждений достигнут. Проверь текущее дело и следующий шаг."
    ),
    EventName.POLL_EXPIRED: (
        "Опрос истёк. Проверь поддержку, пустую категорию и запрос доказательств."
    ),
    EventName.EVIDENCE_ADDED: (
        "Добавлено доказательство. Проверь текущее дело и достаточность фактов."
    ),
    EventName.REQUEST_REGISTERED: (
        "Обращение зарегистрировано. Проверь его статус и применимый срок."
    ),
    EventName.REQUEST_STATUS_CHANGED: (
        "Статус обращения изменился. Проверь фактический статус дела."
    ),
    EventName.REQUEST_DEADLINE_REACHED: (
        "Срок обращения достигнут. Проверь черновик followup и статус."
    ),
    EventName.RESOLUTION_REJECTED: (
        "Житель отклонил результат. Проверь причины и предложи следующий конкретный шаг. "
        "Не удаляй прежние ответы и не закрывай дело автоматически."
    ),
    EventName.DOCUMENT_READY: "Документ готов. Проверь его связь с текущей версией дела.",
}


class ContinuationCaseResolver(Protocol):
    async def resolve(self, event: EventEnvelope) -> tuple[UUID, ExecutionMode] | None: ...


class PostgresContinuationCaseResolver:
    """Ищет дело и режим по house scope; poll/document producer передаёт case_id."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def resolve(self, event: EventEnvelope) -> tuple[UUID, ExecutionMode] | None:
        if event.house_id is None or event.entity is None:
            return None
        async with self.sessions() as session:
            house = await session.get(HouseRow, event.house_id)
            if house is None:
                return None
            case_id = event.entity.case_id or event.entity.entity_id
            case = await session.scalar(
                select(CaseRow).where(CaseRow.id == case_id, CaseRow.house_id == event.house_id)
            )
            if case is None and event.name in {
                EventName.REQUEST_REGISTERED,
                EventName.REQUEST_STATUS_CHANGED,
                EventName.REQUEST_DEADLINE_REACHED,
            }:
                request = await session.scalar(
                    select(RequestRow).where(
                        RequestRow.id == event.entity.entity_id,
                        RequestRow.house_id == event.house_id,
                    )
                )
                if request is not None:
                    case = await session.scalar(
                        select(CaseRow).where(
                            CaseRow.id == request.case_id, CaseRow.house_id == event.house_id
                        )
                    )
            if case is None:
                return None
            return case.id, ExecutionMode.DEMO if house.demo else ExecutionMode.LIVE


class AgentEventHandler:
    """Передаёт модели только тип события; факты дела coordinator читает заново."""

    def __init__(self, resolver: ContinuationCaseResolver, coordinator: AgentCoordinator) -> None:
        self.resolver = resolver
        self.coordinator = coordinator

    async def __call__(self, event: EventEnvelope) -> bool:
        prompt = EVENT_PROMPTS.get(event.name)
        if prompt is None:
            return False
        if event.source not in {EventSource.DOMAIN, EventSource.EXECUTOR, EventSource.SCHEDULER}:
            raise ValueError("UNTRUSTED_CONTINUATION_EVENT")
        if event.house_id is None or event.entity is None:
            raise ValueError("CONTINUATION_CONTEXT_MISSING")
        resolved = await self.resolver.resolve(event)
        if resolved is None:
            raise ValueError("CASE_NOT_FOUND")
        case_id, mode = resolved
        context = TrustedContext(
            run_id=uuid4(),
            event_id=event.event_id,
            house_id=event.house_id,
            actor_id=None,
            principal_type=PrincipalType.WORKER,
            capabilities=frozenset({"case.read", "request.read", "knowledge.read"}),
            correlation_id=event.correlation_id,
            mode=mode,
            case_id=case_id,
        )
        outcome = await self.coordinator.run_event(
            [{"role": "system", "content": prompt}],
            context,
            AgentMode.FOLLOWUP,
            case_id=case_id,
            now=event.received_at,
        )
        if outcome.status != "completed":
            raise RuntimeError("AGENT_CONTINUATION_FAILED")
        return True


def register_agent_events(
    dispatcher: EventDispatcher,
    revisions: RevisionRouter,
    agent: AgentEventHandler,
    deadline: RequestDeadlineHandler,
    deadline_revision: RequestDeadlineRevisionReader,
) -> None:
    """Подключает K handlers к A dispatcher; deadline сначала готовит followup."""

    for event_name in EVENT_PROMPTS:
        if event_name is EventName.REQUEST_DEADLINE_REACHED:
            continue
        dispatcher.register(event_name, agent)

    async def handle_deadline(event: EventEnvelope) -> bool:
        await deadline(event)
        return await agent(event)

    dispatcher.register(EventName.REQUEST_DEADLINE_REACHED, handle_deadline)
    revisions.register(EventName.REQUEST_DEADLINE_REACHED, deadline_revision)
