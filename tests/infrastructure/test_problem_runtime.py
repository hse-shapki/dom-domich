"""A14/K09: созданная обычная проблема автоматически открывает production poll."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from dom_domych.agent.contracts import CaseCreate, CaseKind
from dom_domych.application.cases.production import register_problem_events
from dom_domych.application.documents.production import RequestDocumentEventHandler
from dom_domych.application.jobs.inbox_worker import EventDispatcher, InboxWorker
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.events import (
    EntityEventPayload,
    EventEnvelope,
    EventName,
    EventSource,
)
from dom_domych.domain.polls.models import VoteChoice
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    InboxEventRow,
    OutboxDeliveryRow,
    ScheduledJobRow,
)
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow
from dom_domych.infrastructure.postgres.z_poll_models import PollRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("problem runtime requires dedicated migrated PostgreSQL test database")
    return value


def context() -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=HOUSE_ONE,
        actor_id=synthetic_id("resident-2"),
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset({"case.write"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


def command(title: str) -> CaseCreate:
    return CaseCreate(
        kind=CaseKind.PROBLEM,
        title=title,
        description="Не горит свет на пятом этаже второго подъезда",
        entrance=2,
        floor=5,
        object_name=None,
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )


async def accept_event(_: object) -> bool:
    return True


@pytest.mark.asyncio
async def test_problem_created_event_opens_poll_job_and_card_atomically() -> None:
    clock = FixedClock()
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="-8800555")
            )
        case = await PostgresCaseWriter(sessions, emit_workflow_events=True).create_case(
            command(f"Проверка runtime {uuid4()}"), context(), clock.now()
        )
        dispatcher = EventDispatcher({})
        register_problem_events(dispatcher, sessions, clock)
        worker = InboxWorker(sessions, dispatcher, clock, "problem-runtime")
        assert await worker.run_once()

        async with sessions() as session:
            row = await session.get(CaseRow, case.case_id)
            poll = await session.scalar(select(PollRow).where(PollRow.case_id == case.case_id))
            assert row is not None and row.status == "collecting" and row.version == 2
            assert poll is not None and poll.subject_revision == 1 and poll.status == "open"
            assert await session.get(AudienceSnapshotRow, poll.audience_id) is not None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ScheduledJobRow)
                    .where(ScheduledJobRow.entity_id == poll.id)
                )
                == 1
            )

        request_id, draft_id, source_id, rule_id, responsible_id = (uuid4() for _ in range(5))
        executor_operation_id = uuid4()
        async with sessions.begin() as session:
            session.add(
                KnowledgeSourceRow(
                    source_id=source_id,
                    revision=1,
                    house_id=HOUSE_ONE,
                    title="Демо-правило для PDF",
                    uri="https://example.invalid/problem-runtime",
                    text="Синтетическое проверенное правило",
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
                    topic="lighting",
                    responsible_id=responsible_id,
                )
            )
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=HOUSE_ONE,
                    case_id=case.case_id,
                    draft_id=draft_id,
                    draft_version=1,
                    content_sha256="a" * 64,
                    responsible_id=responsible_id,
                    rule_id=rule_id,
                    source_refs=[f"{source_id}:1"],
                    status="registered",
                    approved_version=1,
                    approval_actor=synthetic_id("resident-2"),
                    executor_operation_id=executor_operation_id,
                    registration_id="DEMO-RUNTIME-1",
                    registered_at=clock.now(),
                    external_status="registered",
                    external_version=1,
                )
            )
        async with sessions.begin() as session:
            state = await PostgresPollRepository(session).get_state(poll.id, HOUSE_ONE)
            assert state is not None
            residents = tuple(state.definition.eligible_residents)
        for resident_id in residents[:3]:
            async with sessions.begin() as session:
                await PostgresPollRepository(session).record_answer_atomic(
                    poll.id,
                    HOUSE_ONE,
                    resident_id,
                    VoteChoice.YES,
                    uuid4(),
                    clock.now(),
                )
        dispatcher.register(EventName.POLL_THRESHOLD_REACHED, accept_event)
        assert await worker.run_once()
        async with sessions() as session:
            updated = await session.get(CaseRow, case.case_id)
            assert updated is not None
            assert updated.status == "request_ready" and updated.version == 3
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxDeliveryRow)
                    .where(OutboxDeliveryRow.operation_key.like(f"problem:{case.case_id}%"))
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxDeliveryRow)
                    .where(
                        OutboxDeliveryRow.house_id == HOUSE_ONE,
                        OutboxDeliveryRow.operation_key == f"problem:{case.case_id}",
                    )
                )
                == 1
            )

        async with sessions.begin() as session:
            registered_case = await session.get(CaseRow, case.case_id)
            assert registered_case is not None
            registered_case.status = "in_progress"
            registered_case.version = 4
        registration_event = EventEnvelope(
            event_id=uuid4(),
            source=EventSource.DOMAIN,
            source_key=f"request-registered:{request_id}",
            name=EventName.REQUEST_REGISTERED,
            occurred_at=clock.now(),
            received_at=clock.now(),
            correlation_id=executor_operation_id,
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(
                entity_id=request_id,
                entity_version=4,
                case_id=case.case_id,
            ),
        )
        document_handler = RequestDocumentEventHandler(sessions, clock)
        assert (
            await document_handler(
                registration_event.model_copy(update={"source": EventSource.EXECUTOR})
            )
            is False
        )
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DocumentRow)
                    .where(DocumentRow.request_id == request_id)
                )
                == 0
            )
        assert await document_handler(registration_event) is False
        assert await document_handler(registration_event) is False
        async with sessions() as session:
            documents = (
                await session.scalars(
                    select(DocumentRow).where(
                        DocumentRow.request_id == request_id,
                        DocumentRow.house_id == HOUSE_ONE,
                    )
                )
            ).all()
            assert len(documents) == 1
            assert documents[0].kind == "appeal" and documents[0].status == "queued"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(InboxEventRow)
                    .where(InboxEventRow.source_key == f"problem-detected:{case.case_id}")
                )
                == 1
            )
        # Не оставляем PDF-задачу этой проверки для следующего document-worker теста.
        async with sessions.begin() as session:
            document = await session.get(DocumentRow, documents[0].id)
            assert document is not None
            document.status = "failed"


@pytest.mark.asyncio
async def test_problem_open_rolls_back_if_group_chat_is_not_configured() -> None:
    clock = FixedClock()
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )
        case = await PostgresCaseWriter(sessions, emit_workflow_events=True).create_case(
            command(f"Проверка rollback {uuid4()}"), context(), clock.now()
        )
        dispatcher = EventDispatcher({})
        register_problem_events(dispatcher, sessions, clock)
        worker = InboxWorker(sessions, dispatcher, clock, "problem-runtime-rollback")
        assert await worker.run_once()

        async with sessions() as session:
            row = await session.get(CaseRow, case.case_id)
            assert row is not None and row.status == "detected" and row.version == 1
            assert (
                await session.scalar(
                    select(func.count()).select_from(PollRow).where(PollRow.case_id == case.case_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AudienceSnapshotRow)
                    .where(AudienceSnapshotRow.operation_key.like(f"%{case.case_id}%"))
                )
                == 0
            )
