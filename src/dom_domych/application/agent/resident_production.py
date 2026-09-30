"""Production use cases явных команд жителя поверх существующих K/Z сервисов."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.contracts import RequestPrepare, RequestSubmit
from dom_domych.application.agent.resident_actions import ResidentAction
from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.cases.evidence import (
    EvidenceAssessment,
    EvidenceAssessmentInput,
    EvidenceInput,
    EvidenceService,
)
from dom_domych.application.executor.production import DemoSubmitAdapter
from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.application.initiatives.service import InitiativeService
from dom_domych.application.requests.service import RequestDraft, RequestService
from dom_domych.contracts.base import TrustedContext
from dom_domych.contracts.events import EventEnvelope
from dom_domych.domain.polls.policy import demo_initiative_policy
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.max.evidence import MaxEvidenceLoader
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_evidence import PostgresEvidenceWriter
from dom_domych.infrastructure.postgres.case_models import (
    CaseEventRow,
    CaseEvidenceRow,
    CaseMessageRow,
    CaseRow,
)
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.initiative_cases import PostgresInitiativeCases
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.knowledge import PostgresKnowledgeRepository
from dom_domych.infrastructure.postgres.request_models import RequestOperationRow
from dom_domych.infrastructure.postgres.requests import PostgresRequestCases, PostgresRequestStore


@dataclass(frozen=True, slots=True)
class _HouseActor:
    house_id: UUID
    actor_id: UUID


class PostgresResidentActions:
    """Проверяет авторство/дом; внешняя загрузка фото идёт вне SQL-транзакции."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        evidence: MaxEvidenceLoader,
        files: LocalFileStore,
    ) -> None:
        self.sessions = sessions
        self.clock = clock
        self.evidence = evidence
        self.files = files
        self.request_store = PostgresRequestStore(sessions, clock)
        self.requests = RequestService(
            PostgresRequestCases(sessions),
            PostgresKnowledgeRepository(sessions),
            self.request_store,
            DemoSubmitAdapter(DemoExecutorService(PostgresDemoExecutor(sessions, clock), clock)),
            clock,
        )

    async def execute(
        self, action: ResidentAction, event: EventEnvelope, context: TrustedContext
    ) -> str:
        if context.actor_id is None or event.message is None:
            raise PermissionError("FORBIDDEN")
        if action.name == "prepare":
            return await self._prepare(action.entity_id, context)
        if action.name == "approve":
            return await self._approve(action.entity_id, context)
        if action.name == "send":
            return await self._send(action.entity_id, context)
        if action.name == "revise":
            assert action.expected_revision is not None and action.wording is not None
            return await self._revise(action, context)
        if action.name == "evidence":
            return await self._evidence(action.entity_id, event, context)
        if action.name == "assess":
            assert action.evidence_id is not None and action.assessment is not None
            return await self._assess(action, context)
        raise ValueError("INVALID_ACTION")

    async def _require_author(
        self, session: AsyncSession, case_id: UUID, context: TrustedContext
    ) -> None:
        actor = await session.scalar(
            select(CaseMessageRow.actor_id).where(
                CaseMessageRow.case_id == case_id,
                CaseMessageRow.house_id == context.house_id,
                CaseMessageRow.relation == "origin",
            )
        )
        if actor != context.actor_id:
            raise PermissionError("FORBIDDEN")

    async def _prepare(self, case_id: UUID, context: TrustedContext) -> str:
        async with self.sessions() as session:
            await self._require_author(session, case_id, context)
            prior = await session.get(RequestOperationRow, (context.house_id, context.event_id))
            if prior is not None:
                draft = await self.request_store.get(prior.request_id, context.house_id)
                if draft is None or draft.case_id != case_id:
                    raise ValueError("CONFLICT")
                return self._prepared_reply(draft.request_id, draft.draft_version)
        case = await PostgresRequestCases(self.sessions).get_for_request(case_id, context.house_id)
        if case is None:
            raise ValueError("CASE_NOT_FOUND")
        rule = await PostgresKnowledgeRepository(self.sessions).find_rule(
            case.topic, context.house_id, self.clock.now()
        )
        if rule is None:
            return (
                "Для этого дела пока нет проверенного правила и ответственного. "
                "Обращение не подготовлено."
            )
        prepared = await self.requests.prepare(
            RequestPrepare(
                case_id=case_id,
                expected_case_version=case.version,
                responsible_id=rule.responsible_id,
                source_refs=(f"{rule.source_id}:{rule.source_revision}",),
                operation_id=context.event_id,
            ),
            context.model_copy(update={"capabilities": context.capabilities | {"request.write"}}),
        )
        return (
            self._prepared_reply(prepared.request_id, prepared.draft_version)
            + f"\nДело: {case.title}. {case.description[:1200]}"
            + f"\nМесто: {case.location}. Ответственный: {rule.responsible_id}."
            + f"\nПроверенный источник: {rule.source_id}:{rule.source_revision}."
        )

    @staticmethod
    def _prepared_reply(request_id: UUID, version: int) -> str:
        return (
            f"Черновик демо-обращения {request_id}, версия {version}, подготовлен. "
            f"Проверьте данные ниже, затем отправьте в личке /approve {request_id}. "
            f"После согласования — /send {request_id}."
        )

    async def _request_for_author(self, request_id: UUID, context: TrustedContext) -> RequestDraft:
        draft = await self.request_store.get(request_id, context.house_id)
        if draft is None:
            raise ValueError("REQUEST_NOT_FOUND")
        async with self.sessions() as session:
            await self._require_author(session, draft.case_id, context)
        return draft

    async def _approve(self, request_id: UUID, context: TrustedContext) -> str:
        draft = await self._request_for_author(request_id, context)
        approved = await self.requests.approve(
            request_id,
            draft.draft_version,
            context.model_copy(update={"capabilities": context.capabilities | {"request.approve"}}),
        )
        return (
            f"Версия {approved.draft_version} демо-обращения {request_id} согласована. "
            f"Для передачи тестовому исполнителю отправьте /send {request_id}."
        )

    async def _send(self, request_id: UUID, context: TrustedContext) -> str:
        draft = await self._request_for_author(request_id, context)
        if draft.approval_actor != context.actor_id:
            raise PermissionError("FORBIDDEN")
        submitted = await self.requests.submit(
            RequestSubmit(
                request_id=request_id,
                expected_draft_version=draft.draft_version,
                operation_id=context.event_id,
            ),
            context.model_copy(update={"capabilities": context.capabilities | {"request.submit"}}),
        )
        return (
            f"Демо-обращение {request_id}: {submitted.status}. "
            "Это передача тестовому исполнителю, не регистрация в УК."
        )

    async def _revise(self, action: ResidentAction, context: TrustedContext) -> str:
        assert context.actor_id is not None
        assert action.expected_revision is not None and action.wording is not None
        repository = PostgresInitiativeRepository(self.sessions)
        operation_key = f"initiative:revision:message:{context.event_id}"
        prior = await repository.get_operation_result(context.house_id, operation_key)
        if prior is not None:
            if (
                prior.case_id != action.entity_id
                or prior.author_id != context.actor_id
                or prior.current.revision != action.expected_revision + 1
                or prior.current.wording != action.wording
            ):
                raise ValueError("CONFLICT")
            return f"Инициатива {action.entity_id}: редакция {prior.current.revision} открыта."
        state = await repository.get(action.entity_id, context.house_id)
        if state.author_id != context.actor_id:
            raise PermissionError("FORBIDDEN")
        if state.current.revision != action.expected_revision:
            raise ValueError("REVISION_CONFLICT")
        async with self.sessions.begin() as session:
            audience_repo = PostgresAudienceRepository(session)
            previous = await audience_repo.get_scoped(state.current.audience_id, context.house_id)
            if previous is None:
                raise ValueError("AUDIENCE_NOT_FOUND")
            audience = await AudienceService(
                PostgresHouseContext(session, self.clock), audience_repo, self.clock
            ).resolve(
                previous.scope,
                _HouseActor(context.house_id, context.actor_id),
                operation_key=f"initiative:audience:revision:{context.event_id}",
                supersedes_id=previous.audience_id,
            )
        revised = await InitiativeService(
            PostgresInitiativeCases(self.sessions), repository, self.clock
        ).revise(
            action.entity_id,
            action.wording,
            audience,
            demo_initiative_policy(),
            timedelta(days=2),
            _HouseActor(context.house_id, context.actor_id),
            expected_revision=action.expected_revision,
            operation_key=operation_key,
        )
        return (
            f"Инициатива {action.entity_id}: редакция {revised.current.revision} открыта. "
            "Голоса старой редакции отменены; жители получат новое приглашение."
        )

    async def _evidence(self, case_id: UUID, event: EventEnvelope, context: TrustedContext) -> str:
        assert context.actor_id is not None
        async with self.sessions() as session:
            previous = await session.scalar(
                select(CaseEvidenceRow.id).where(
                    CaseEvidenceRow.case_id == case_id,
                    CaseEvidenceRow.house_id == context.house_id,
                    CaseEvidenceRow.actor_id == context.actor_id,
                    CaseEvidenceRow.source_ref == f"event:{event.event_id}",
                )
            )
            if previous is not None:
                return self._evidence_reply(case_id, previous)
        async with self.sessions() as session:
            case = await session.scalar(
                select(CaseRow).where(CaseRow.id == case_id, CaseRow.house_id == context.house_id)
            )
            if case is None or case.status == "closed":
                raise ValueError("CASE_NOT_FOUND")
            version = case.version
        files = await self.evidence.load_images(event.event_id, context.house_id)
        if len(files) != 1:
            for item in files:
                await self.files.delete(context.house_id, item.file_key)
            raise ValueError("ONE_IMAGE_REQUIRED")
        stored = files[0]
        try:
            await EvidenceService(PostgresEvidenceWriter(self.sessions), self.clock).add(
                EvidenceInput(case_id, version, stored.file_key, event.event_id),
                context.model_copy(
                    update={"capabilities": context.capabilities | {"evidence.write"}}
                ),
            )
        except Exception:
            await self.files.delete(context.house_id, stored.file_key)
            raise
        async with self.sessions() as session:
            evidence_id = await session.scalar(
                select(CaseEvidenceRow.id).where(
                    CaseEvidenceRow.case_id == case_id,
                    CaseEvidenceRow.house_id == context.house_id,
                    CaseEvidenceRow.source_ref == f"event:{event.event_id}",
                )
            )
        assert evidence_id is not None
        return self._evidence_reply(case_id, evidence_id)

    @staticmethod
    def _evidence_reply(case_id: UUID, evidence_id: UUID) -> str:
        return (
            f"Фото {evidence_id} сохранено в деле {case_id} без анализа изображения. "
            f"Чтобы подтвердить, что оно относится к проблеме, отправьте "
            f"/assess {case_id} {evidence_id} accepted; для отказа — rejected."
        )

    async def _assess(self, action: ResidentAction, context: TrustedContext) -> str:
        assert action.evidence_id is not None and action.assessment is not None
        async with self.sessions() as session:
            prior = await session.scalar(
                select(CaseEventRow).where(
                    CaseEventRow.house_id == context.house_id,
                    CaseEventRow.operation_id == context.event_id,
                    CaseEventRow.case_id == action.entity_id,
                    CaseEventRow.event_type == "evidence.assessed",
                )
            )
            if prior is not None:
                if (
                    prior.facts.get("evidence_id") != str(action.evidence_id)
                    or prior.facts.get("assessment") != action.assessment
                    or prior.actor_id != context.actor_id
                ):
                    raise ValueError("CONFLICT")
                return f"Оценка фото {action.evidence_id} уже сохранена."
            evidence = await session.get(CaseEvidenceRow, action.evidence_id)
            case = await session.scalar(
                select(CaseRow).where(
                    CaseRow.id == action.entity_id,
                    CaseRow.house_id == context.house_id,
                )
            )
            if (
                evidence is None
                or evidence.case_id != action.entity_id
                or evidence.house_id != context.house_id
                or evidence.actor_id != context.actor_id
                or evidence.assessment != "pending"
                or case is None
                or case.status == "closed"
            ):
                raise PermissionError("FORBIDDEN")
            version = case.version
            source_ref = evidence.source_ref
        await EvidenceService(PostgresEvidenceWriter(self.sessions), self.clock).assess(
            EvidenceAssessmentInput(
                case_id=action.entity_id,
                evidence_id=action.evidence_id,
                expected_version=version,
                assessment=EvidenceAssessment(action.assessment),
                source_refs=(source_ref,),
                operation_id=context.event_id,
            ),
            context.model_copy(update={"capabilities": context.capabilities | {"evidence.assess"}}),
        )
        return (
            f"Ваша оценка фото {action.evidence_id} сохранена: {action.assessment}. "
            "Это не автоматическая проверка изображения и не отправка обращения."
        )
