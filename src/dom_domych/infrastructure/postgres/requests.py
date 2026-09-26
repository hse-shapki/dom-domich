"""K10: короткие транзакции черновика и доверенной demo-регистрации."""

from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.requests.service import Clock, RequestCase, RequestDraft
from dom_domych.contracts.events import (
    EntityEventPayload,
    EventEnvelope,
    EventName,
    EventSource,
)
from dom_domych.domain.executor.models import DemoOperation
from dom_domych.domain.ports.core import JobIntent
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.inbox import save_domain_event
from dom_domych.infrastructure.postgres.jobs import PostgresJobQueue
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.request_models import RequestOperationRow, RequestRow


def _draft(row: RequestRow) -> RequestDraft:
    return RequestDraft(
        request_id=row.id,
        draft_id=row.draft_id,
        case_id=row.case_id,
        house_id=row.house_id,
        draft_version=row.draft_version,
        content_sha256=row.content_sha256,
        responsible_id=row.responsible_id,
        rule_id=row.rule_id,
        source_refs=tuple(row.source_refs),
        status=row.status,
        approved_version=row.approved_version,
        approval_actor=row.approval_actor,
        executor_operation_id=row.executor_operation_id,
        registration_id=row.registration_id,
        registered_at=row.registered_at,
    )


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class PostgresRequestCases:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_for_request(self, case_id: UUID, house_id: UUID) -> RequestCase | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(CaseRow).where(CaseRow.id == case_id, CaseRow.house_id == house_id)
            )
            if row is None:
                return None
            location = ""
            if row.entrance is not None:
                location = f"подъезд {row.entrance}"
                if row.floor is not None:
                    location += f", этаж {row.floor}"
            return RequestCase(
                case_id=row.id,
                house_id=row.house_id,
                kind=row.kind,
                version=row.version,
                status=row.status,
                topic=row.object_name or "",
                title=row.title,
                description=row.description,
                location=location,
            )


class PostgresRequestStore:
    """Executor вызывается приложением вне транзакций; здесь только короткие записи."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    @staticmethod
    async def _operation_lock(session: AsyncSession, house_id: UUID, operation_id: UUID) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"request:{house_id}:{operation_id}"},
        )

    @staticmethod
    async def _prior(
        session: AsyncSession, house_id: UUID, operation_id: UUID, command_hash: str
    ) -> RequestDraft | None:
        prior = await session.get(RequestOperationRow, (house_id, operation_id))
        if prior is None:
            return None
        if prior.command_hash != command_hash:
            raise ValueError("CONFLICT")
        row = await session.get(RequestRow, prior.request_id)
        if row is None or row.house_id != house_id:
            raise ValueError("REQUEST_NOT_FOUND")
        return _draft(row)

    async def get(self, request_id: UUID, house_id: UUID) -> RequestDraft | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == request_id, RequestRow.house_id == house_id
                )
            )
            return _draft(row) if row is not None else None

    async def get_prepare_operation(
        self, house_id: UUID, operation_id: UUID, command_hash: str
    ) -> RequestDraft | None:
        async with self.sessions() as session:
            return await self._prior(session, house_id, operation_id, command_hash)

    async def prepare_once(
        self,
        draft: RequestDraft,
        expected_case_version: int,
        operation_id: UUID,
        command_hash: str,
    ) -> RequestDraft:
        async with self.sessions.begin() as session:
            await self._operation_lock(session, draft.house_id, operation_id)
            prior = await self._prior(session, draft.house_id, operation_id, command_hash)
            if prior is not None:
                return prior
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == draft.case_id, CaseRow.house_id == draft.house_id)
                .with_for_update()
            )
            if case is None or case.version != expected_case_version:
                raise ValueError("VERSION_CONFLICT")
            if case.status not in {"request_ready", "detected", "preparing_request"}:
                raise ValueError("INVALID_STATE")
            existing = await session.scalar(
                select(RequestRow).where(
                    RequestRow.case_id == draft.case_id,
                    RequestRow.house_id == draft.house_id,
                    RequestRow.status != "registered",
                )
            )
            if existing is not None:
                raise ValueError("CONFLICT")
            request = RequestRow(
                id=draft.request_id,
                house_id=draft.house_id,
                case_id=draft.case_id,
                draft_id=draft.draft_id,
                draft_version=1,
                content_sha256=draft.content_sha256,
                responsible_id=draft.responsible_id,
                rule_id=draft.rule_id,
                source_refs=list(draft.source_refs),
                status="prepared",
                approved_version=None,
                approval_actor=None,
                submit_operation_id=None,
                executor_operation_id=None,
                registration_id=None,
                registered_at=None,
            )
            session.add(request)
            await session.flush()
            previous_version = case.version
            case.version += 1
            case.status = "awaiting_approval"
            session.add(
                CaseEventRow(
                    id=uuid4(),
                    case_id=case.id,
                    house_id=draft.house_id,
                    event_type="request.prepared",
                    before_version=previous_version,
                    after_version=case.version,
                    actor_id=None,
                    source_message_id=None,
                    operation_id=operation_id,
                    occurred_at=self.clock.now(),
                    facts={"request_id": str(request.id), "draft_version": 1},
                )
            )
            session.add(
                RequestOperationRow(
                    house_id=draft.house_id,
                    operation_id=operation_id,
                    request_id=request.id,
                    command_hash=command_hash,
                    result_view=draft.to_view().model_dump(mode="json"),
                )
            )
            return _draft(request)

    async def revise(
        self,
        request_id: UUID,
        house_id: UUID,
        expected_version: int,
        content_sha256: str,
        operation_id: UUID,
    ) -> RequestDraft:
        command_hash = _hash((request_id, expected_version, content_sha256))
        async with self.sessions.begin() as session:
            await self._operation_lock(session, house_id, operation_id)
            prior = await self._prior(session, house_id, operation_id, command_hash)
            if prior is not None:
                return prior
            row = await session.scalar(
                select(RequestRow)
                .where(RequestRow.id == request_id, RequestRow.house_id == house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("REQUEST_NOT_FOUND")
            if row.draft_version != expected_version:
                raise ValueError("VERSION_CONFLICT")
            if row.status not in {"prepared", "approved"}:
                raise ValueError("INVALID_STATE")
            row.draft_version += 1
            row.content_sha256 = content_sha256
            row.status = "prepared"
            row.approved_version = None
            row.approval_actor = None
            session.add(
                RequestOperationRow(
                    house_id=house_id,
                    operation_id=operation_id,
                    request_id=request_id,
                    command_hash=command_hash,
                    result_view=_draft(row).to_view().model_dump(mode="json"),
                )
            )
            return _draft(row)

    async def approve(
        self, request_id: UUID, house_id: UUID, expected_version: int, actor_id: UUID
    ) -> RequestDraft:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(RequestRow)
                .where(RequestRow.id == request_id, RequestRow.house_id == house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("REQUEST_NOT_FOUND")
            if row.draft_version != expected_version:
                raise ValueError("VERSION_CONFLICT")
            if row.status == "approved" and row.approval_actor == actor_id:
                return _draft(row)
            if row.status != "prepared":
                raise ValueError("INVALID_STATE")
            row.approved_version = expected_version
            row.approval_actor = actor_id
            row.status = "approved"
            return _draft(row)

    async def reserve_submit(
        self, request_id: UUID, house_id: UUID, expected_version: int, operation_id: UUID
    ) -> RequestDraft:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(RequestRow)
                .where(RequestRow.id == request_id, RequestRow.house_id == house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("REQUEST_NOT_FOUND")
            if row.draft_version != expected_version:
                raise ValueError("VERSION_CONFLICT")
            if row.submit_operation_id == operation_id and row.status in {
                "submitting",
                "submitted",
                "registered",
            }:
                return _draft(row)
            if row.status != "approved" or row.approved_version != row.draft_version:
                raise ValueError("APPROVAL_REQUIRED")
            row.submit_operation_id = operation_id
            row.status = "submitting"
            return _draft(row)

    async def mark_submitted(
        self, request_id: UUID, house_id: UUID, operation_id: UUID, executor_operation_id: UUID
    ) -> RequestDraft:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(RequestRow)
                .where(RequestRow.id == request_id, RequestRow.house_id == house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("REQUEST_NOT_FOUND")
            if row.submit_operation_id != operation_id:
                raise ValueError("CONFLICT")
            if row.status == "submitted" and row.executor_operation_id == executor_operation_id:
                return _draft(row)
            if row.status != "submitting":
                raise ValueError("INVALID_STATE")
            row.executor_operation_id = executor_operation_id
            row.status = "submitted"
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == row.case_id, CaseRow.house_id == house_id)
                .with_for_update()
            )
            if case is None:
                raise ValueError("CASE_NOT_FOUND")
            previous_version = case.version
            case.version += 1
            case.status = "awaiting_registration"
            session.add(
                CaseEventRow(
                    id=uuid4(),
                    case_id=case.id,
                    house_id=house_id,
                    event_type="request.submitted",
                    before_version=previous_version,
                    after_version=case.version,
                    actor_id=None,
                    source_message_id=None,
                    operation_id=operation_id,
                    occurred_at=self.clock.now(),
                    facts={
                        "request_id": str(request_id),
                        "executor_operation_id": str(executor_operation_id),
                    },
                )
            )
            return _draft(row)

    async def register(
        self, request_id: UUID, house_id: UUID, operation: DemoOperation
    ) -> RequestDraft:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(RequestRow)
                .where(RequestRow.id == request_id, RequestRow.house_id == house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("REQUEST_NOT_FOUND")
            if (
                row.executor_operation_id != operation.operation_id
                or row.draft_id != operation.draft.draft_id
                or row.draft_version != operation.draft.draft_revision
                or row.content_sha256 != operation.draft.content_sha256
            ):
                raise ValueError("EXECUTOR_RESULT_MISMATCH")
            if row.status == "registered":
                if row.registration_id != operation.registration_number:
                    raise ValueError("CONFLICT")
                return _draft(row)
            if row.status != "submitted" or operation.registered_at is None:
                raise ValueError("INVALID_STATE")
            row.registration_id = operation.registration_number
            row.registered_at = operation.registered_at
            row.status = "registered"
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == row.case_id, CaseRow.house_id == house_id)
                .with_for_update()
            )
            if case is None:
                raise ValueError("CASE_NOT_FOUND")
            previous_version = case.version
            case.version += 1
            case.status = "in_progress"
            registration_event_id = uuid4()
            session.add(
                CaseEventRow(
                    id=registration_event_id,
                    case_id=case.id,
                    house_id=house_id,
                    event_type="request.registered",
                    before_version=previous_version,
                    after_version=case.version,
                    actor_id=None,
                    source_message_id=None,
                    operation_id=operation.operation_id,
                    occurred_at=operation.registered_at,
                    facts={"request_id": str(request_id), "registration_id": row.registration_id},
                )
            )
            await save_domain_event(
                session,
                EventEnvelope(
                    event_id=registration_event_id,
                    source=EventSource.DOMAIN,
                    source_key=f"request-registered:{request_id}",
                    name=EventName.REQUEST_REGISTERED,
                    occurred_at=operation.registered_at,
                    received_at=self.clock.now(),
                    correlation_id=operation.operation_id,
                    house_id=house_id,
                    entity=EntityEventPayload(
                        entity_id=request_id,
                        entity_version=case.version,
                        case_id=case.id,
                    ),
                ),
            )
            rule = await session.get(RuleVersionRow, row.rule_id)
            if rule is not None and rule.duration_seconds is not None:
                source = await session.get(
                    KnowledgeSourceRow, (rule.source_id, rule.source_revision)
                )
                registered_at = operation.registered_at
                if (
                    registered_at is not None
                    and rule.duration_seconds > 0
                    and rule.deadline_origin == EventName.REQUEST_REGISTERED.value
                    and rule.responsible_id == row.responsible_id
                    and rule.house_id in {None, house_id}
                    and (rule.valid_from is None or rule.valid_from <= registered_at)
                    and (rule.valid_until is None or registered_at < rule.valid_until)
                    and source is not None
                    and source.reviewed
                    and source.house_id in {None, house_id}
                    and (source.valid_from is None or source.valid_from <= registered_at)
                    and (source.valid_until is None or registered_at < source.valid_until)
                ):
                    await PostgresJobQueue(session).enqueue(
                        JobIntent(
                            house_id=house_id,
                            operation_key=f"request-deadline:{request_id}:{row.registration_id}",
                            event_name=EventName.REQUEST_DEADLINE_REACHED.value,
                            due_at=registered_at + timedelta(seconds=rule.duration_seconds),
                            entity_id=request_id,
                            expected_version=case.version,
                        )
                    )
            return _draft(row)
