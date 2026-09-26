"""K14: общий A scheduler и K deadline/agent на PostgreSQL без MAX и модели."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.agent.llm import FakeLlmPort, LlmResponse
from dom_domych.application.agent.composition import (
    build_k_coordinator,
    register_k_continuations,
)
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.jobs.scheduler import JobScheduler, RevisionRouter
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation
from dom_domych.domain.ports.core import DocumentRef, JobIntent, RequestRef
from dom_domych.infrastructure.postgres.agent_models import AgentRunRow
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.jobs import PostgresJobQueue
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow, ScheduledJobRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.session import database_lifespan


class MovingClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


class UnusedExecutor:
    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation:
        raise AssertionError("deadline continuation must not submit a request")

    async def get_status(self, request_id: UUID, house_id: UUID) -> RequestRef:
        raise AssertionError("deadline continuation must not read an external status")


class UnusedDocuments:
    async def get(self, document_id: UUID, house_id: UUID) -> DocumentRef | None:
        raise AssertionError("deadline continuation must not read a document")


@pytest.mark.asyncio
async def test_registered_request_deadline_dispatches_fresh_run_once() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, other_house = uuid4(), uuid4()
    case_id, request_id, source_id, rule_id, responsible_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC).replace(microsecond=0)
    clock = MovingClock(now + timedelta(seconds=3))
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add_all(
                [
                    HouseRow(id=house_id, address="K14 дом", timezone="UTC", demo=True),
                    HouseRow(id=other_house, address="K14 чужой", timezone="UTC", demo=True),
                ]
            )
            await session.flush()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=house_id,
                    kind="problem",
                    title="Нет света",
                    description="Нет света в первом подъезде",
                    entrance=1,
                    floor=2,
                    object_name="lighting",
                    status="in_progress",
                    version=4,
                    created_at=now,
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
                    title="DEMO: правило",
                    uri="https://example.test/rule",
                    text="Демо срок",
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
                    duration_seconds=2,
                    deadline_origin="request.registered",
                    valid_from=None,
                    valid_until=None,
                )
            )
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=house_id,
                    case_id=case_id,
                    draft_id=uuid4(),
                    draft_version=1,
                    content_sha256="a" * 64,
                    responsible_id=responsible_id,
                    rule_id=rule_id,
                    source_refs=[f"{source_id}:1"],
                    status="registered",
                    approved_version=1,
                    approval_actor=None,
                    submit_operation_id=uuid4(),
                    executor_operation_id=uuid4(),
                    registration_id="DEMO-K14",
                    registered_at=now,
                )
            )
        try:
            async with sessions.begin() as session:
                job_id = await PostgresJobQueue(session).enqueue(
                    JobIntent(
                        house_id=house_id,
                        operation_key=f"k14:{request_id}",
                        event_name=EventName.REQUEST_DEADLINE_REACHED.value,
                        due_at=now + timedelta(seconds=2),
                        entity_id=request_id,
                        expected_version=4,
                    )
                )
            llm = FakeLlmPort([LlmResponse("Нужно проверить черновик и статус")])
            coordinator = build_k_coordinator(sessions, llm, clock, UnusedExecutor())
            dispatcher, revisions = EventDispatcher({}), RevisionRouter()
            register_k_continuations(
                dispatcher,
                revisions,
                sessions,
                clock,
                coordinator,
                UnusedExecutor(),
                UnusedDocuments(),
            )
            scheduler = JobScheduler(sessions, dispatcher, revisions, clock, "k14-worker")
            assert await scheduler.run_once()
            assert not await scheduler.run_once()
            assert llm.call_count == 1
            async with sessions() as session:
                case = await session.get(CaseRow, case_id)
                job = await session.get(ScheduledJobRow, job_id)
                run = await session.scalar(
                    select(AgentRunRow).where(
                        AgentRunRow.house_id == house_id, AgentRunRow.case_id == case_id
                    )
                )
                assert case is not None and case.status == "followup_draft" and case.version == 5
                assert job is not None and job.status == "done"
                assert run is not None and run.status == "completed" and run.case_version == 5
            foreign_event = EventEnvelope(
                event_id=uuid4(),
                source=EventSource.DOMAIN,
                source_key="foreign:k14",
                name=EventName.RESOLUTION_REJECTED,
                occurred_at=clock.now(),
                received_at=clock.now(),
                correlation_id=uuid4(),
                house_id=other_house,
                entity=EntityEventPayload(entity_id=case_id, entity_version=5),
            )
            with pytest.raises(ValueError, match="CASE_NOT_FOUND"):
                await dispatcher.handle(foreign_event)
            async with sessions.begin() as session:
                stale_id = await PostgresJobQueue(session).enqueue(
                    JobIntent(
                        house_id=house_id,
                        operation_key=f"k14-stale:{request_id}",
                        event_name=EventName.REQUEST_DEADLINE_REACHED.value,
                        due_at=now + timedelta(seconds=2),
                        entity_id=request_id,
                        expected_version=4,
                    )
                )
            assert await scheduler.run_once()
            async with sessions() as session:
                stale = await session.get(ScheduledJobRow, stale_id)
                assert stale is not None and stale.status == "skipped_stale"
            assert llm.call_count == 1
        finally:
            async with sessions.begin() as session:
                await session.execute(delete(AgentRunRow).where(AgentRunRow.house_id == house_id))
                await session.execute(
                    delete(ScheduledJobRow).where(ScheduledJobRow.entity_id == request_id)
                )
                await session.execute(delete(CaseEventRow).where(CaseEventRow.case_id == case_id))
                await session.execute(delete(RequestRow).where(RequestRow.id == request_id))
                await session.execute(delete(CaseRow).where(CaseRow.id == case_id))
                await session.execute(delete(RuleVersionRow).where(RuleVersionRow.id == rule_id))
                await session.execute(
                    delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_id == source_id)
                )
                await session.execute(
                    delete(HouseRow).where(HouseRow.id.in_([house_id, other_house]))
                )
