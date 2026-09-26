"""K10: подготовка, ревизия, approval, submit и registration на PostgreSQL."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.agent.contracts import RequestPrepare, RequestSubmit, TrustedContext
from dom_domych.application.requests.deadline import (
    RequestDeadlineHandler,
    RequestDeadlineRevisionReader,
)
from dom_domych.application.requests.service import RequestService
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation, ExternalStatus
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.jobs import DueJob
from dom_domych.infrastructure.postgres.knowledge import PostgresKnowledgeRepository
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow, ResidentRow, ScheduledJobRow
from dom_domych.infrastructure.postgres.request_models import RequestOperationRow, RequestRow
from dom_domych.infrastructure.postgres.requests import PostgresRequestCases, PostgresRequestStore
from dom_domych.infrastructure.postgres.session import database_lifespan

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class LaterClock:
    def now(self) -> datetime:
        return NOW + timedelta(seconds=61)


class FakeExecutor:
    def __init__(self) -> None:
        self.operations: dict[str, DemoOperation] = {}

    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation:
        if draft.house_id != house_id:
            raise ValueError("WRONG_HOUSE")
        if operation_key not in self.operations:
            self.operations[operation_key] = DemoOperation(
                uuid4(), operation_key, draft, ExternalStatus.SUBMITTED, NOW
            )
        return self.operations[operation_key]


def _context(house_id: UUID, actor_id: UUID, *, worker: bool = False) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=house_id,
        actor_id=actor_id,
        principal_type=PrincipalType.WORKER if worker else PrincipalType.RESIDENT,
        capabilities=frozenset(
            {"request.record_registration"}
            if worker
            else {"request.write", "request.approve", "request.submit", "request.read"}
        ),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


@pytest.mark.asyncio
async def test_request_lifecycle_requires_reviewed_rule_and_real_registration() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, other_house, actor_id = uuid4(), uuid4(), uuid4()
    case_id, source_id, rule_id, responsible_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add_all(
                [
                    HouseRow(id=house_id, address="K10 дом", timezone="UTC", demo=True),
                    HouseRow(id=other_house, address="K10 чужой", timezone="UTC", demo=True),
                    ResidentRow(id=actor_id, display_name="Житель K10", active_house_id=house_id),
                ]
            )
        async with sessions.begin() as session:
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=house_id,
                    kind="problem",
                    title="Нет света",
                    description="На лестнице нет освещения",
                    entrance=1,
                    floor=3,
                    object_name="lighting",
                    status="request_ready",
                    version=1,
                    created_at=NOW,
                    closed_at=None,
                    recurrence_of=None,
                    embedding=None,
                    embedding_revision=None,
                )
            )
            session.add(
                KnowledgeSourceRow(
                    source_id=source_id,
                    revision=1,
                    house_id=house_id,
                    title="Ответственность",
                    uri="https://example.gov.ru/source",
                    text="Ответственный назначен",
                    reviewed=True,
                    valid_from=None,
                    valid_until=None,
                )
            )
        async with sessions.begin() as session:
            session.add(
                RuleVersionRow(
                    id=rule_id,
                    source_id=source_id,
                    source_revision=1,
                    house_id=house_id,
                    topic="lighting",
                    responsible_id=responsible_id,
                    duration_seconds=60,
                    deadline_origin="request.registered",
                    valid_from=None,
                    valid_until=None,
                )
            )
        try:
            executor = FakeExecutor()
            service = RequestService(
                PostgresRequestCases(sessions),
                PostgresKnowledgeRepository(sessions),
                PostgresRequestStore(sessions, FixedClock()),
                executor,
                FixedClock(),
            )
            context = _context(house_id, actor_id)
            command = RequestPrepare(
                case_id=case_id,
                expected_case_version=1,
                responsible_id=responsible_id,
                source_refs=(f"{source_id}:1",),
                operation_id=uuid4(),
            )
            with pytest.raises(ValueError, match="UNVERIFIED_RESPONSIBLE"):
                await service.prepare(
                    command.model_copy(update={"responsible_id": uuid4(), "operation_id": uuid4()}),
                    context,
                )
            prepared = await service.prepare(command, context)
            assert prepared.status == "prepared" and prepared.registered_at is None
            assert await service.prepare(command, context) == prepared
            assert (
                await service.get_status(prepared.request_id, _context(other_house, actor_id))
                is None
            )
            with pytest.raises(ValueError, match="APPROVAL_REQUIRED"):
                await service.submit(
                    RequestSubmit(
                        request_id=prepared.request_id,
                        expected_draft_version=1,
                        operation_id=uuid4(),
                    ),
                    context,
                )
            approved = await service.approve(prepared.request_id, 1, context)
            assert approved.status == "approved"
            revised = await service.revise(
                prepared.request_id, 1, "Новая версия черновика обращения", uuid4(), context
            )
            assert revised.draft_version == 2 and revised.status == "prepared"
            await service.approve(prepared.request_id, 2, context)
            submit = RequestSubmit(
                request_id=prepared.request_id, expected_draft_version=2, operation_id=uuid4()
            )
            submitted = await service.submit(submit, context)
            assert submitted.status == "submitted" and submitted.registration_id is None
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(ScheduledJobRow).where(
                            ScheduledJobRow.entity_id == prepared.request_id
                        )
                    )
                    is None
                )
            assert await service.submit(submit, context) == submitted
            assert len(executor.operations) == 1
            with pytest.raises(PermissionError):
                await service.record_registration(
                    next(iter(executor.operations.values())),
                    _context(house_id, actor_id, worker=True),
                )
            operation, changed = next(iter(executor.operations.values())).register(NOW)
            assert changed
            registered = await service.record_registration(
                operation, _context(house_id, actor_id, worker=True)
            )
            assert registered.status == "registered"
            assert registered.registration_id == operation.registration_number
            assert (
                await service.record_registration(
                    operation, _context(house_id, actor_id, worker=True)
                )
                == registered
            )
            async with sessions() as session:
                case = await session.get(CaseRow, case_id)
                assert case is not None and case.status == "in_progress"
                job = await session.scalar(
                    select(ScheduledJobRow).where(ScheduledJobRow.entity_id == prepared.request_id)
                )
                assert job is not None
                assert job.due_at == NOW + timedelta(seconds=60)
                assert job.event_name == EventName.REQUEST_DEADLINE_REACHED.value
                job_id, version = job.id, job.expected_version
            reader = RequestDeadlineRevisionReader(sessions)
            due = DueJob(
                job_id,
                house_id,
                EventName.REQUEST_DEADLINE_REACHED,
                prepared.request_id,
                version,
                NOW + timedelta(seconds=60),
                1,
            )
            assert await reader.current_version(due) == version
            event = EventEnvelope(
                event_id=job_id,
                source=EventSource.SCHEDULER,
                source_key=f"job:{job_id}",
                name=EventName.REQUEST_DEADLINE_REACHED,
                occurred_at=NOW + timedelta(seconds=60),
                received_at=NOW + timedelta(seconds=61),
                correlation_id=job_id,
                house_id=house_id,
                entity=EntityEventPayload(entity_id=prepared.request_id, entity_version=version),
            )
            handler = RequestDeadlineHandler(sessions, LaterClock())
            await handler(
                event.model_copy(
                    update={
                        "entity": EntityEventPayload(
                            entity_id=prepared.request_id,
                            entity_version=version + 1,
                        )
                    }
                )
            )
            assert await reader.current_version(due) == version
            await handler(event)
            await handler(event)
            assert await reader.current_version(due) is None
            async with sessions() as session:
                case = await session.get(CaseRow, case_id)
                assert case is not None and case.status == "followup_draft"
                assert case.version == version + 1
                followups = (
                    await session.scalars(
                        select(CaseEventRow).where(
                            CaseEventRow.case_id == case_id,
                            CaseEventRow.event_type == EventName.REQUEST_DEADLINE_REACHED.value,
                        )
                    )
                ).all()
                assert len(followups) == 1
                assert followups[0].facts["draft_status"] == "needs_review"
            async with sessions.begin() as session:
                case = await session.get(CaseRow, case_id)
                assert case is not None
                case.status = "closed"
                case.closed_at = NOW + timedelta(seconds=62)
                case.version += 1
            closed_event = event.model_copy(
                update={
                    "event_id": uuid4(),
                    "entity": EntityEventPayload(
                        entity_id=prepared.request_id,
                        entity_version=version + 2,
                    ),
                }
            )
            await handler(closed_event)
            async with sessions() as session:
                assert (
                    len(
                        (
                            await session.scalars(
                                select(CaseEventRow).where(
                                    CaseEventRow.case_id == case_id,
                                    CaseEventRow.event_type
                                    == EventName.REQUEST_DEADLINE_REACHED.value,
                                )
                            )
                        ).all()
                    )
                    == 1
                )
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(ScheduledJobRow).where(ScheduledJobRow.entity_id == prepared.request_id)
                )
                await session.execute(
                    delete(RequestOperationRow).where(RequestOperationRow.house_id == house_id)
                )
                await session.execute(delete(RequestRow).where(RequestRow.house_id == house_id))
                await session.execute(delete(CaseEventRow).where(CaseEventRow.house_id == house_id))
                await session.execute(delete(CaseRow).where(CaseRow.id == case_id))
                await session.execute(delete(RuleVersionRow).where(RuleVersionRow.id == rule_id))
                await session.execute(
                    delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_id == source_id)
                )
                await session.execute(delete(ResidentRow).where(ResidentRow.id == actor_id))
                await session.execute(
                    delete(HouseRow).where(HouseRow.id.in_([house_id, other_house]))
                )
