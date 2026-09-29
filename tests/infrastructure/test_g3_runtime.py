"""A14: локальная production-цепь от проблемы до подтверждённого закрытия."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import or_, select, update

from dom_domych.agent.contracts import CaseCreate, CaseKind, RequestPrepare, RequestSubmit
from dom_domych.application.cases.production import register_problem_events
from dom_domych.application.documents.production import RequestDocumentEventHandler
from dom_domych.application.documents.worker import DocumentWorker
from dom_domych.application.executor.production import DemoSubmitAdapter
from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.application.jobs.inbox_worker import EventDispatcher, InboxWorker
from dom_domych.application.jobs.scheduler import RevisionRouter
from dom_domych.application.requests.events import RequestEventHandler, register_request_events
from dom_domych.application.requests.service import RequestService
from dom_domych.application.resolution.production import register_z_poll_events
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.executor.models import ExternalStatus
from dom_domych.domain.polls.models import PollKind, PollStatus, VoteChoice
from dom_domych.infrastructure.documents.renderer import PdfRenderer
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.demo_executor import (
    PostgresDemoExecutor,
    PostgresExecutorPort,
)
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
from dom_domych.infrastructure.postgres.knowledge import PostgresKnowledgeRepository
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, ScheduledJobRow
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.requests import PostgresRequestCases, PostgresRequestStore
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow
from dom_domych.infrastructure.postgres.z_poll_models import PollRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 28, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


@dataclass(frozen=True)
class ExecutorContext:
    house_id: UUID
    capabilities: frozenset[str]


async def accept_event(_: object) -> bool:
    return True


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("G3 runtime requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_problem_request_executor_resolution_closes_through_runtime(
    tmp_path: Path,
) -> None:
    clock = FixedClock()
    actor_id = synthetic_id("resident-2")
    topic = f"lighting-{uuid4()}"
    resident_context = TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=HOUSE_ONE,
        actor_id=actor_id,
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset(
            {"case.write", "request.write", "request.approve", "request.submit", "request.read"}
        ),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )
    command = CaseCreate(
        kind=CaseKind.PROBLEM,
        title=f"G3 освещение {uuid4()}",
        description="Не горит свет на пятом этаже второго подъезда",
        entrance=2,
        floor=5,
        object_name=topic,
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="8800999")
            )
        case = await PostgresCaseWriter(sessions, emit_workflow_events=True).create_case(
            command, resident_context, clock.now()
        )
        problem_dispatcher = EventDispatcher({})
        register_problem_events(problem_dispatcher, sessions, clock)
        problem_dispatcher.register(EventName.POLL_THRESHOLD_REACHED, accept_event)
        worker = InboxWorker(sessions, problem_dispatcher, clock, "g3-problem")
        assert await worker.run_once()
        async with sessions.begin() as session:
            origin = await session.scalar(select(PollRow).where(PollRow.case_id == case.case_id))
            assert origin is not None
            state = await PostgresPollRepository(session).get_state(origin.id, HOUSE_ONE)
            assert state is not None and state.definition.eligible_residents
            eligible_residents = tuple(state.definition.eligible_residents)
        threshold_emitted = False
        for resident_id in eligible_residents:
            async with sessions.begin() as session:
                mutation = await PostgresPollRepository(session).record_answer_atomic(
                    origin.id, HOUSE_ONE, resident_id, VoteChoice.YES, uuid4(), clock.now()
                )
            if "poll.threshold_reached" in mutation.events:
                threshold_emitted = True
                break
        assert threshold_emitted
        assert await worker.run_once()

        source_id, rule_id, responsible_id = uuid4(), uuid4(), uuid4()
        async with sessions.begin() as session:
            session.add(
                KnowledgeSourceRow(
                    source_id=source_id,
                    revision=1,
                    house_id=HOUSE_ONE,
                    title="Демо-правило G3",
                    uri="https://example.invalid/g3-runtime",
                    text="Синтетический ответственный",
                    reviewed=True,
                )
            )
            await session.flush()
            session.add(
                RuleVersionRow(
                    id=rule_id,
                    source_id=source_id,
                    source_revision=1,
                    house_id=HOUSE_ONE,
                    topic=topic,
                    responsible_id=responsible_id,
                )
            )

        executor_store = PostgresDemoExecutor(sessions, clock)
        request_store = PostgresRequestStore(sessions, clock)
        requests = RequestService(
            PostgresRequestCases(sessions),
            PostgresKnowledgeRepository(sessions),
            request_store,
            DemoSubmitAdapter(DemoExecutorService(executor_store, clock)),
            clock,
        )
        prepared = await requests.prepare(
            RequestPrepare(
                case_id=case.case_id,
                expected_case_version=3,
                responsible_id=responsible_id,
                source_refs=(f"{source_id}:1",),
                operation_id=uuid4(),
            ),
            resident_context,
        )
        await requests.approve(prepared.request_id, 1, resident_context)
        submitted = await requests.submit(
            RequestSubmit(
                request_id=prepared.request_id,
                expected_draft_version=1,
                operation_id=uuid4(),
            ),
            resident_context,
        )
        async with sessions() as session:
            request = await session.get(RequestRow, submitted.request_id)
            assert request is not None and request.executor_operation_id is not None
            executor_operation_id = request.executor_operation_id

        executor = DemoExecutorService(executor_store, clock)
        registration_context = ExecutorContext(HOUSE_ONE, frozenset({"demo_executor.register"}))
        operator_context = ExecutorContext(HOUSE_ONE, frozenset({"demo_executor.operator"}))
        registered, emitted = await executor.register(executor_operation_id, registration_context)
        assert emitted and registered.registration_number is not None

        dispatcher, revisions = EventDispatcher({}), RevisionRouter()
        resolution = register_z_poll_events(dispatcher, revisions, sessions, clock)
        dispatcher.register(
            EventName.REQUEST_REGISTERED, RequestDocumentEventHandler(sessions, clock)
        )
        dispatcher.register(EventName.REQUEST_REGISTERED, accept_event)
        register_request_events(
            dispatcher,
            RequestEventHandler(
                PostgresExecutorPort(executor_store),
                PostgresDocuments(sessions),
                request_store,
            ),
        )
        dispatcher.register(EventName.REQUEST_STATUS_CHANGED, resolution.handle_status)
        dispatcher.register(EventName.REQUEST_STATUS_CHANGED, accept_event)
        dispatcher.register(EventName.DOCUMENT_READY, accept_event)
        dispatcher.register(EventName.POLL_EXPIRED, accept_event)
        runtime_worker = InboxWorker(sessions, dispatcher, clock, "g3-runtime")
        assert await runtime_worker.run_once()  # executor request.registered
        assert await runtime_worker.run_once()  # domain request.registered + appeal snapshot
        async with sessions() as session:
            document = await session.scalar(
                select(DocumentRow).where(DocumentRow.request_id == prepared.request_id)
            )
            assert document is not None
            frozen_bytes = document.snapshot_bytes
            document_id = document.id
        clock.current += timedelta(minutes=3)
        replay = EventEnvelope(
            event_id=uuid4(),
            source=EventSource.DOMAIN,
            source_key=f"replay:{uuid4()}",
            name=EventName.REQUEST_REGISTERED,
            occurred_at=clock.now(),
            received_at=clock.now(),
            correlation_id=uuid4(),
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(
                entity_id=prepared.request_id, entity_version=1, case_id=case.case_id
            ),
        )
        assert not await RequestDocumentEventHandler(sessions, clock)(replay)
        async with sessions() as session:
            document = await session.scalar(
                select(DocumentRow).where(DocumentRow.request_id == prepared.request_id)
            )
            assert document is not None and document.id == document_id
            assert document.snapshot_bytes == frozen_bytes
        async with PdfRenderer(max_workers=1) as renderer:
            document_worker = DocumentWorker(
                sessions,
                LocalFileStore(tmp_path / "files", clock),
                renderer,
                clock,
                "g3-documents",
            )
            assert await document_worker.run_once()
        assert await runtime_worker.run_once()  # document.ready + request binding

        done_event_id = uuid4()
        done, emitted = await executor.set_status(
            executor_operation_id, ExternalStatus.DONE, done_event_id, operator_context
        )
        assert emitted and done.status is ExternalStatus.DONE
        assert await runtime_worker.run_once()

        async with sessions() as session:
            resolution_poll = await session.scalar(
                select(PollRow).where(
                    PollRow.case_id == case.case_id,
                    PollRow.kind == PollKind.RESOLUTION_CHECK.value,
                )
            )
            assert resolution_poll is not None
            case_row = await session.get(CaseRow, case.case_id)
            assert case_row is not None and case_row.status == "checking_resolution"
        async with sessions.begin() as session:
            state = await PostgresPollRepository(session).get_state(resolution_poll.id, HOUSE_ONE)
            assert state is not None
            for resident_id in state.definition.eligible_residents:
                await PostgresPollRepository(session).record_answer_atomic(
                    resolution_poll.id,
                    HOUSE_ONE,
                    resident_id,
                    VoteChoice.YES,
                    uuid4(),
                    clock.now(),
                )
            finalized = await PostgresPollRepository(session).finalize_atomic(
                resolution_poll.id, HOUSE_ONE, resolution_poll.closes_at
            )
            assert finalized.state.status is PollStatus.CLOSED
        clock.current = resolution_poll.closes_at
        assert await runtime_worker.run_once()

        async with sessions.begin() as session:
            closed = await session.get(CaseRow, case.case_id)
            assert closed is not None and closed.status == "closed"
            request = await session.get(RequestRow, prepared.request_id)
            assert request is not None and request.external_status == "done"
            document = await session.scalar(
                select(DocumentRow).where(DocumentRow.request_id == prepared.request_id)
            )
            assert document is not None and document.status == "ready"
            assert request.document_id == document.id
            assert request.document_file_key == document.file_key
            await session.execute(
                update(ScheduledJobRow)
                .where(
                    ScheduledJobRow.entity_id.in_((origin.id, resolution_poll.id)),
                    ScheduledJobRow.status == "pending",
                )
                .values(status="done")
            )
            await session.execute(
                update(OutboxDeliveryRow)
                .where(
                    OutboxDeliveryRow.status == "pending",
                    or_(
                        OutboxDeliveryRow.operation_key.like(f"%{case.case_id}%"),
                        OutboxDeliveryRow.operation_key.like(f"%{executor_operation_id}%"),
                        OutboxDeliveryRow.operation_key.like(f"%{resolution_poll.id}%"),
                        OutboxDeliveryRow.operation_key.like(f"%{document.id}%"),
                    ),
                )
                .values(status="sent")
            )
