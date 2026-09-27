"""A14/K09: созданная обычная проблема автоматически открывает production poll."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from dom_domych.agent.contracts import CaseCreate, CaseKind
from dom_domych.application.cases.production import register_problem_events
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


@pytest.mark.asyncio
async def test_problem_created_event_opens_poll_job_and_card_atomically() -> None:
    clock = FixedClock()
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id="8800555")
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
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(InboxEventRow)
                    .where(InboxEventRow.source_key == f"problem-detected:{case.case_id}")
                )
                == 1
            )


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
