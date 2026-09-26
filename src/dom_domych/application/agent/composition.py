"""K composition: production services, tools и continuations поверх общих A ports."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.continuation import AgentCoordinator, ContextBuilder
from dom_domych.agent.contracts import KnowledgeHit, KnowledgeSearch, TrustedContext
from dom_domych.agent.llm import LlmPort
from dom_domych.agent.runtime import AgentRuntime
from dom_domych.agent.tool_handlers import KToolHandlers
from dom_domych.agent.tools import build_k_tool_definitions
from dom_domych.agent.triage import LlmTriagePort, TriageService
from dom_domych.application.agent.events import (
    AgentEventHandler,
    PostgresContinuationCaseResolver,
    register_agent_events,
)
from dom_domych.application.agent.messages import MessageAgentHandler
from dom_domych.application.cases.candidates import CandidateService
from dom_domych.application.cases.service import CaseService
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.jobs.scheduler import RevisionRouter
from dom_domych.application.knowledge.service import KnowledgeService
from dom_domych.application.requests.deadline import (
    RequestDeadlineHandler,
    RequestDeadlineRevisionReader,
)
from dom_domych.application.requests.emergency import EmergencyService
from dom_domych.application.requests.events import RequestEventHandler, register_request_events
from dom_domych.application.requests.service import DemoSubmitPort, RequestService
from dom_domych.domain.knowledge.ports import EmbeddingPort
from dom_domych.domain.ports.core import Clock, DocumentPort, ExecutorPort
from dom_domych.infrastructure.postgres.agent_runs import PostgresRunStore
from dom_domych.infrastructure.postgres.case_candidates import PostgresCaseReader
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.emergency_evidence import PostgresEmergencyEvidenceQueue
from dom_domych.infrastructure.postgres.knowledge import PostgresKnowledgeRepository
from dom_domych.infrastructure.postgres.message_agent import (
    PostgresMessagePrincipals,
    PostgresMessageReplies,
)
from dom_domych.infrastructure.postgres.requests import (
    PostgresRequestCases,
    PostgresRequestStore,
)


class ClockedKnowledgePort:
    """Подставляет backend-время: модель не выбирает момент применимости правила."""

    def __init__(self, service: KnowledgeService, clock: Clock) -> None:
        self.service = service
        self.clock = clock

    async def search(
        self, command: KnowledgeSearch, context: TrustedContext
    ) -> tuple[KnowledgeHit, ...]:
        return await self.service.search(command, context, at=self.clock.now())


def build_k_tool_handlers(
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    executor: DemoSubmitPort,
    *,
    embeddings: EmbeddingPort | None = None,
) -> KToolHandlers:
    """Собирает K handlers на PostgreSQL; внешний demo executor остаётся инъекцией Z."""

    reader = PostgresCaseReader(sessions)
    cases = CaseService(
        CandidateService(reader, embeddings),
        PostgresCaseWriter(sessions),
        clock,
    )
    knowledge_repository = PostgresKnowledgeRepository(sessions)
    knowledge = ClockedKnowledgePort(
        KnowledgeService(knowledge_repository, frozenset(), embeddings),
        clock,
    )
    request_cases = PostgresRequestCases(sessions)
    requests = RequestService(
        request_cases,
        knowledge_repository,
        PostgresRequestStore(sessions, clock),
        executor,
        clock,
    )
    emergencies = EmergencyService(
        request_cases,
        knowledge_repository,
        requests,
        PostgresEmergencyEvidenceQueue(sessions, clock),
        clock,
    )
    return KToolHandlers(cases, knowledge, requests, emergencies)


def build_k_coordinator(
    sessions: async_sessionmaker[AsyncSession],
    llm: LlmPort,
    clock: Clock,
    executor: DemoSubmitPort,
    *,
    embeddings: EmbeddingPort | None = None,
) -> AgentCoordinator:
    """Создаёт coordinator с production K repositories и единым tool registry."""

    handlers = build_k_tool_handlers(sessions, clock, executor, embeddings=embeddings)
    runtime = AgentRuntime(llm, build_k_tool_definitions(handlers))
    return AgentCoordinator(
        ContextBuilder(
            handlers.cases,
            PostgresRunStore(sessions),
        ),
        runtime,
    )


def build_k_message_agent(
    sessions: async_sessionmaker[AsyncSession],
    llm: LlmPort,
    clock: Clock,
    coordinator: AgentCoordinator,
    resident_capabilities: frozenset[str],
    *,
    embeddings: EmbeddingPort | None = None,
) -> MessageAgentHandler:
    """Собирает message handler; набор прав задаёт composition root, не модель."""

    knowledge = KnowledgeService(
        PostgresKnowledgeRepository(sessions),
        frozenset(),
        embeddings,
    )
    return MessageAgentHandler(
        PostgresMessagePrincipals(sessions, clock, resident_capabilities),
        TriageService(LlmTriagePort(llm), knowledge),
        coordinator,
        PostgresMessageReplies(sessions, clock),
    )


def register_k_continuations(
    dispatcher: EventDispatcher,
    revisions: RevisionRouter,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    coordinator: AgentCoordinator,
    executor: ExecutorPort,
    documents: DocumentPort,
) -> None:
    """Регистрирует mutation handlers раньше continuation и deadline revision reader."""

    register_request_events(
        dispatcher,
        RequestEventHandler(executor, documents, PostgresRequestStore(sessions, clock)),
    )
    register_agent_events(
        dispatcher,
        revisions,
        AgentEventHandler(PostgresContinuationCaseResolver(sessions), coordinator),
        RequestDeadlineHandler(sessions, clock),
        RequestDeadlineRevisionReader(sessions),
    )
