"""A14/Z06: созданная инициатива автоматически открывает production poll."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from dom_domych.agent.contracts import CaseCreate, CaseKind
from dom_domych.application.initiatives.production import register_initiative_events
from dom_domych.application.jobs.inbox_worker import EventDispatcher, InboxWorker
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    InboxEventRow,
    OutboxDeliveryRow,
    ScheduledJobRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_initiative_models import (
    InitiativeRevisionRow,
    InitiativeRow,
)
from dom_domych.infrastructure.postgres.z_poll_models import PollRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("initiative runtime requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_initiative_event_opens_audience_poll_reminders_and_card_atomically() -> None:
    clock = FixedClock()
    author_id = synthetic_id("resident-2")
    context = TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=HOUSE_ONE,
        actor_id=author_id,
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset({"case.write"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )
    command = CaseCreate(
        kind=CaseKind.INITIATIVE,
        title=f"Велопарковка {uuid4()}",
        description="Установить у второго подъезда велопарковку на шесть мест",
        entrance=2,
        floor=None,
        object_name=None,
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="8800777")
            )
        case = await PostgresCaseWriter(sessions, emit_workflow_events=True).create_case(
            command, context, clock.now()
        )
        dispatcher = EventDispatcher({})
        register_initiative_events(dispatcher, sessions, clock)
        worker = InboxWorker(sessions, dispatcher, clock, "initiative-runtime")
        assert await worker.run_once()

        async with sessions.begin() as session:
            case_row = await session.get(CaseRow, case.case_id)
            initiative = await session.get(InitiativeRow, case.case_id)
            revision = await session.get(InitiativeRevisionRow, (case.case_id, 1))
            poll = await session.scalar(select(PollRow).where(PollRow.case_id == case.case_id))
            assert case_row is not None
            assert case_row.status == "collecting" and case_row.version == 2
            assert initiative is not None
            assert initiative.author_id == author_id and initiative.case_version == 2
            assert revision is not None and revision.wording == command.description
            assert poll is not None
            assert poll.kind == "initiative_position" and poll.subject_revision == 1
            assert await session.get(AudienceSnapshotRow, poll.audience_id) is not None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ScheduledJobRow)
                    .where(ScheduledJobRow.entity_id == poll.id)
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxDeliveryRow)
                    .where(OutboxDeliveryRow.operation_key == f"initiative:{case.case_id}")
                )
                == 1
            )
            event = await session.scalar(
                select(InboxEventRow).where(
                    InboxEventRow.source_key == f"initiative-detected:{case.case_id}"
                )
            )
            assert event is not None and event.status == "done"

            # Не оставляем due/outbox этой проверки для следующих queue-тестов общего набора.
            await session.execute(
                update(ScheduledJobRow)
                .where(ScheduledJobRow.entity_id == poll.id)
                .values(status="done")
            )
            await session.execute(
                update(OutboxDeliveryRow)
                .where(
                    OutboxDeliveryRow.operation_key.like(f"poll:invite:{poll.id}:%")
                    | (OutboxDeliveryRow.operation_key == f"initiative:{case.case_id}")
                )
                .values(status="sent")
            )
