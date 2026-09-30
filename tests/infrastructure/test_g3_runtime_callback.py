"""A14: локальная production-цепь от проблемы до подтверждённого закрытия."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
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
from dom_domych.application.polls.callback import CallbackStatus
from dom_domych.application.polls.production import PostgresPollCallbackProcessor
from dom_domych.application.requests.events import RequestEventHandler, register_request_events
from dom_domych.application.requests.service import RequestService
from dom_domych.application.resolution.production import register_z_poll_events
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.events import (
    CallbackPayload,
    EventEnvelope,
    EventName,
    EventSource,
)
from dom_domych.domain.executor.models import ExternalStatus
from dom_domych.domain.polls.models import PollKind, PollStatus, VoteChoice
from dom_domych.infrastructure.documents.renderer import PdfRenderer
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.demo_executor import (
    PostgresDemoExecutor,
    PostgresExecutorPort,
)
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
from dom_domych.infrastructure.postgres.knowledge import PostgresKnowledgeRepository
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    OutboxDeliveryRow,
    ResidentRow,
    ScheduledJobRow,
)
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
@pytest.mark.parametrize(
    ("resolution_choice", "expected_status"),
    [(VoteChoice.YES, "closed"), (VoteChoice.NO, "reopened")],
)
async def test_problem_callback_card_request_pdf_and_resolution_through_runtime(
    tmp_path: Path, resolution_choice: VoteChoice, expected_status: str
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
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="-8800999")
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
        async with sessions.begin() as session:
            card = await session.scalar(
                select(OutboxDeliveryRow).where(
                    OutboxDeliveryRow.house_id == HOUSE_ONE,
                    OutboxDeliveryRow.operation_key == f"problem:{case.case_id}",
                )
            )
            assert card is not None and len(card.buttons) == 2
            yes_token = card.buttons[0]["payload"]
            max_actors = {}
            for index, resident_id in enumerate(eligible_residents[:3], start=1):
                max_user_id = str(900000000 + index)
                max_actors[resident_id] = max_user_id
                await session.execute(
                    update(ResidentRow)
                    .where(ResidentRow.id == resident_id)
                    .values(max_user_id=max_user_id)
                )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"success": True})
            ),
            base_url="https://platform-api2.max.ru",
        ) as http:
            callback_processor = PostgresPollCallbackProcessor(
                sessions, MaxApiClient(http, "synthetic-token"), clock
            )
            for max_user_id in max_actors.values():
                event_id = uuid4()
                callback = EventEnvelope(
                    event_id=event_id,
                    source=EventSource.MAX,
                    source_key=f"g3:callback:{event_id}",
                    name=EventName.CALLBACK_RECEIVED,
                    occurred_at=clock.now(),
                    received_at=clock.now(),
                    correlation_id=event_id,
                    actor_user_id=max_user_id,
                    callback=CallbackPayload(
                        callback_id=str(event_id),
                        sender_user_id=max_user_id,
                        action_token=yes_token,
                        chat_id="-8800999",
                    ),
                )
                assert (
                    await callback_processor.process(callback)
                ).status is CallbackStatus.RECORDED
        async with sessions() as session:
            state = await PostgresPollRepository(session).get_state(origin.id, HOUSE_ONE)
            assert state is not None and state.tally.yes == 3
            edits = (
                await session.scalars(
                    select(OutboxDeliveryRow).where(
                        OutboxDeliveryRow.edit_key == f"problem:{case.case_id}"
                    )
                )
            ).all()
            assert len(edits) == 3
            latest = next(item for item in edits if item.status == "pending")
            assert "Поддержали 3 из 12 жителей" in latest.text
            assert all(str(resident_id) not in latest.text for resident_id in eligible_residents)
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
                    resolution_choice,
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
            settled = await session.get(CaseRow, case.case_id)
            assert settled is not None and settled.status == expected_status
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
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id.in_(tuple(max_actors)))
                .values(max_user_id=None)
            )
