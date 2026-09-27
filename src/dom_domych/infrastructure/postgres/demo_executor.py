"""Транзакционный demo executor с доверенной проверкой утверждённого черновика."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.executor.models import (
    ApprovedDraft,
    DemoOperation,
    ExecutorConflict,
    ExecutorNotFound,
    ExternalStatus,
)
from dom_domych.domain.ports.core import Clock, DeliveryIntent, RequestRef
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import InboxEventRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.z_executor_models import DemoExecutorRow


def _operation(row: DemoExecutorRow) -> DemoOperation:
    return DemoOperation(
        operation_id=row.id,
        operation_key=row.operation_key,
        draft=ApprovedDraft(
            row.house_id,
            row.request_id,
            row.draft_id,
            row.draft_revision,
            row.content_sha256,
        ),
        status=ExternalStatus(row.status),
        submitted_at=row.submitted_at,
        registration_number=row.registration_number,
        registered_at=row.registered_at,
        status_updated_at=row.status_updated_at,
        processed_event_ids=frozenset(UUID(value) for value in row.processed_event_ids),
    )


class PostgresDemoExecutor:
    """Каждая команда открывает UoW; событие и outbox пишутся с изменением статуса."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def submit_once(self, operation: DemoOperation) -> DemoOperation:
        draft = operation.draft
        if not operation.operation_key or len(operation.operation_key) > 250:
            raise ValueError("invalid demo executor operation key")
        async with self.sessions.begin() as session:
            prior = await session.scalar(
                select(DemoExecutorRow).where(
                    DemoExecutorRow.house_id == draft.house_id,
                    DemoExecutorRow.operation_key == operation.operation_key,
                )
            )
            if prior is not None:
                return self._matching(prior, draft)
            request = await session.scalar(
                select(RequestRow)
                .where(RequestRow.id == draft.request_id, RequestRow.house_id == draft.house_id)
                .with_for_update()
            )
            if request is None:
                raise ExecutorNotFound("approved request is not available for this house")
            if (
                request.draft_id != draft.draft_id
                or request.draft_version != draft.draft_revision
                or request.content_sha256 != draft.content_sha256
                or request.approved_version != draft.draft_revision
                or request.status not in {"approved", "submitting"}
            ):
                raise ExecutorConflict("draft is not the current approved request version")
            inserted = await session.scalar(
                insert(DemoExecutorRow)
                .values(
                    id=operation.operation_id,
                    house_id=draft.house_id,
                    request_id=draft.request_id,
                    operation_key=operation.operation_key,
                    draft_id=draft.draft_id,
                    draft_revision=draft.draft_revision,
                    content_sha256=draft.content_sha256,
                    status=ExternalStatus.SUBMITTED.value,
                    submitted_at=operation.submitted_at,
                    processed_event_ids=[],
                )
                .on_conflict_do_nothing()
                .returning(DemoExecutorRow.id)
            )
            if inserted is not None:
                return operation
            prior = await session.scalar(
                select(DemoExecutorRow).where(
                    DemoExecutorRow.house_id == draft.house_id,
                    DemoExecutorRow.operation_key == operation.operation_key,
                )
            )
            if prior is None:
                raise ExecutorConflict("request already has a demo submission")
            return self._matching(prior, draft)

    @staticmethod
    def _matching(row: DemoExecutorRow, draft: ApprovedDraft) -> DemoOperation:
        if _operation(row).draft != draft:
            raise ExecutorConflict("operation key was used for another draft")
        return _operation(row)

    async def register_atomic(
        self, house_id: UUID, operation_id: UUID, at: datetime
    ) -> tuple[DemoOperation, bool]:
        async with self.sessions.begin() as session:
            row = await self._locked(session, house_id, operation_id)
            changed, emitted = _operation(row).register(at)
            if not emitted:
                return changed, False
            row.status = changed.status.value
            row.registration_number = changed.registration_number
            row.registered_at = changed.registered_at
            row.status_updated_at = changed.status_updated_at
            request = await session.get(RequestRow, row.request_id)
            if request is None:
                raise ExecutorNotFound("request disappeared")
            await self._event(session, row, request, EventName.REQUEST_REGISTERED, uuid4(), 1, at)
            await self._notify(session, row, request, "Демо-обращение зарегистрировано")
            return changed, True

    async def change_status_atomic(
        self,
        house_id: UUID,
        operation_id: UUID,
        status: ExternalStatus,
        at: datetime,
        source_event_id: UUID,
    ) -> tuple[DemoOperation, bool]:
        async with self.sessions.begin() as session:
            row = await self._locked(session, house_id, operation_id)
            changed, emitted = _operation(row).change_status(status, at, source_event_id)
            if not emitted:
                return changed, False
            row.status = changed.status.value
            row.status_updated_at = changed.status_updated_at
            row.processed_event_ids = [str(item) for item in sorted(changed.processed_event_ids)]
            request = await session.get(RequestRow, row.request_id)
            if request is None:
                raise ExecutorNotFound("request disappeared")
            await self._event(
                session,
                row,
                request,
                EventName.REQUEST_STATUS_CHANGED,
                source_event_id,
                len(changed.processed_event_ids) + 1,
                at,
            )
            await self._notify(session, row, request, f"Демо-статус исполнителя: {status.value}")
            return changed, True

    async def get(self, house_id: UUID, request_id: UUID) -> DemoOperation:
        async with self.sessions() as session:
            row = await session.scalar(
                select(DemoExecutorRow).where(
                    DemoExecutorRow.house_id == house_id,
                    DemoExecutorRow.request_id == request_id,
                )
            )
            if row is None:
                raise ExecutorNotFound("request is not registered for this house")
            return _operation(row)

    @staticmethod
    async def _locked(session: AsyncSession, house_id: UUID, operation_id: UUID) -> DemoExecutorRow:
        row = await session.scalar(
            select(DemoExecutorRow)
            .where(DemoExecutorRow.id == operation_id, DemoExecutorRow.house_id == house_id)
            .with_for_update()
        )
        if row is None:
            raise ExecutorNotFound("operation is not available for this house")
        return row

    async def _event(
        self,
        session: AsyncSession,
        row: DemoExecutorRow,
        request: RequestRow,
        name: EventName,
        event_id: UUID,
        version: int,
        at: datetime,
    ) -> None:
        event = EventEnvelope(
            event_id=event_id,
            source=EventSource.EXECUTOR,
            source_key=f"executor:{name.value}:{event_id}",
            name=name,
            occurred_at=at,
            received_at=at,
            correlation_id=row.id,
            house_id=row.house_id,
            entity=EntityEventPayload(
                entity_id=row.request_id,
                entity_version=version,
                case_id=request.case_id,
                causation_id=row.id,
            ),
        )
        await session.execute(
            insert(InboxEventRow)
            .values(
                id=event.event_id,
                source="executor",
                source_key=event.source_key,
                event_name=event.name.value,
                house_id=row.house_id,
                raw_update={},
                normalized_event=event.model_dump(mode="json"),
                received_at=at,
                available_at=at,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=["source", "source_key"])
        )

    async def _notify(
        self, session: AsyncSession, row: DemoExecutorRow, request: RequestRow, text: str
    ) -> None:
        if request.approval_actor is None:
            return
        await PostgresDeliveryQueue(session, self.clock).enqueue(
            DeliveryIntent(
                house_id=row.house_id,
                operation_key=f"executor:notice:{row.id}:{row.status}",
                text=f"{text}. Источник: demo_executor; это моделируемое действие.",
                recipient_id=request.approval_actor,
            )
        )


class PostgresExecutorPort:
    """Узкий K13-порт: возвращает статус по request, не подменяя workflow."""

    def __init__(self, store: PostgresDemoExecutor) -> None:
        self.store = store

    async def get_status(self, request_id: UUID, house_id: UUID) -> RequestRef:
        operation = await self.store.get(house_id, request_id)
        async with self.store.sessions() as session:
            request = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == request_id, RequestRow.house_id == house_id
                )
            )
            if request is None:
                raise ExecutorNotFound("request is not available for this house")
            return RequestRef(
                request_id=request.id,
                case_id=request.case_id,
                house_id=house_id,
                version=len(operation.processed_event_ids) + 1,
                external_status=operation.status.value,
            )
