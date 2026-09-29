"""Z04: конкурентные голоса, frozen policy и срок в PostgreSQL."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.polls.service import PollService
from dom_domych.contracts.events import EventName
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.models import AnswerStatus, PollKind, PollStatus, VoteChoice
from dom_domych.domain.polls.policy import ProblemOutcome, demo_problem_policy
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.jobs import DueJob
from dom_domych.infrastructure.postgres.models import (
    InboxEventRow,
    OutboxDeliveryRow,
    ScheduledJobRow,
)
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import (
    PostgresPollRepository,
    PostgresPollRevisionReader,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_poll_models import PollAnswerHistoryRow, PollAnswerRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO


@dataclass(frozen=True)
class Context:
    house_id: UUID


@dataclass(frozen=True)
class ActorContext:
    house_id: UUID
    actor_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_concurrent_answers_record_one_vote_and_one_threshold_event() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z04 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            case_id = uuid4()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="problem",
                    title="Тестовый опрос",
                    description="Тест",
                    status="collecting",
                    version=1,
                    created_at=clock.now(),
                )
            )
            audience = await AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                Context(HOUSE_ONE),
                operation_key=f"z04:audience:{case_id}",
            )
            opened = await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.PROBLEM_CONFIRMATION,
                demo_problem_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z04:poll:{case_id}",
            )
            poll_id = opened.definition.poll_id
            residents = tuple(member.resident_id for member in audience.members)
        async with sessions() as session:
            persisted = await PostgresPollRepository(session).get_state(poll_id, HOUSE_ONE)
            assert persisted == opened
            assert await PostgresPollRepository(session).get_state(poll_id, HOUSE_TWO) is None
            notices = (
                await session.scalars(
                    select(OutboxDeliveryRow).where(
                        OutboxDeliveryRow.operation_key.like(f"poll:invite:{poll_id}:%")
                    )
                )
            ).all()
            assert len(notices) == audience.eligible_count == 12
            for notice in notices:
                assert notice.recipient_id in opened.definition.eligible_residents
                assert notice.chat_id is None and len(notice.buttons) == 2
                action = await PostgresPollActionStore(session).get(notice.buttons[0]["payload"])
                assert action is not None and action.bound_resident_id == notice.recipient_id
                assert action.poll_id == poll_id and action.subject_revision == 1
            job = await session.scalar(
                select(ScheduledJobRow).where(ScheduledJobRow.entity_id == poll_id)
            )
            assert job is not None
            assert job.due_at == opened.definition.closes_at
            assert (
                await PostgresPollRevisionReader(sessions).current_version(
                    DueJob(
                        job.id,
                        HOUSE_ONE,
                        EventName.POLL_EXPIRED,
                        poll_id,
                        1,
                        job.due_at,
                        0,
                    )
                )
                == 1
            )

        async def answer(actor_id: UUID, source_event_id: UUID) -> AnswerStatus:
            async with sessions.begin() as session:
                mutation = await PollService(PostgresPollRepository(session), clock).record_answer(
                    poll_id,
                    VoteChoice.YES,
                    source_event_id,
                    clock.now() + timedelta(minutes=1),
                    ActorContext(HOUSE_ONE, actor_id),
                )
                assert mutation.answer_result is not None
                return mutation.answer_result.status

        repeated = await asyncio.gather(*(answer(residents[0], uuid4()) for _ in range(12)))
        assert repeated.count(AnswerStatus.RECORDED) == 1
        assert repeated.count(AnswerStatus.DUPLICATE) == 11
        await asyncio.gather(answer(residents[1], uuid4()), answer(residents[2], uuid4()))
        async with sessions() as session:
            final = await PostgresPollRepository(session).get_state(poll_id, HOUSE_ONE)
            assert final is not None
            assert final.tally.yes == 3
            assert final.status == PollStatus.CLOSED
            assert final.outcome == ProblemOutcome.REQUEST_READY
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PollAnswerRow)
                    .where(PollAnswerRow.poll_id == poll_id)
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PollAnswerHistoryRow)
                    .where(PollAnswerHistoryRow.poll_id == poll_id)
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(InboxEventRow)
                    .where(
                        InboxEventRow.source == "domain",
                        InboxEventRow.source_key == f"poll:{poll_id}:poll.threshold_reached",
                    )
                )
                == 1
            )


@pytest.mark.asyncio
async def test_deadline_finalizes_only_after_predate_callbacks_are_drained() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z04 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            case_id = uuid4()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="problem",
                    title="Тест срока",
                    description="Тест",
                    status="collecting",
                    version=1,
                    created_at=clock.now(),
                )
            )
            audience = await AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                Context(HOUSE_ONE),
                operation_key=f"z04:audience:{case_id}",
            )
            poll = await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.PROBLEM_CONFIRMATION,
                demo_problem_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z04:poll:{case_id}",
            )
            poll_id = poll.definition.poll_id
        callback_id = uuid4()
        async with sessions.begin() as session:
            session.add(
                InboxEventRow(
                    id=callback_id,
                    source="max",
                    source_key=f"z04:callback:{callback_id}",
                    event_name="callback.received",
                    house_id=HOUSE_ONE,
                    raw_update={},
                    normalized_event={},
                    received_at=clock.now() + timedelta(minutes=1),
                    status="pending",
                    available_at=clock.now(),
                )
            )
        with pytest.raises(ValueError, match="POLL_INBOX_NOT_DRAINED"):
            async with sessions.begin() as session:
                await PostgresPollRepository(session).finalize_atomic(
                    poll_id, HOUSE_ONE, clock.now() + timedelta(hours=5)
                )
        async with sessions.begin() as session:
            row = await session.get(InboxEventRow, callback_id)
            assert row is not None
            row.status = "done"
        async with sessions.begin() as session:
            mutation = await PostgresPollRepository(session).finalize_atomic(
                poll_id, HOUSE_ONE, clock.now() + timedelta(hours=5)
            )
            assert mutation.state.outcome == ProblemOutcome.NEED_EVIDENCE
        async with sessions.begin() as session:
            repeated = await PostgresPollRepository(session).finalize_atomic(
                poll_id, HOUSE_ONE, clock.now() + timedelta(hours=6)
            )
            assert repeated.events == ()
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(InboxEventRow)
                    .where(
                        InboxEventRow.source == "domain",
                        InboxEventRow.source_key == f"poll:{poll_id}:poll.expired",
                    )
                )
                == 1
            )
