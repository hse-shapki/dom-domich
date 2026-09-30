"""Z08: ограниченные напоминания и итог позиции в PostgreSQL/outbox."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.initiatives.followup import (
    InitiativeFollowupService,
    demo_reminder_policy,
)
from dom_domych.application.initiatives.service import InitiativeService
from dom_domych.application.resolution.production import PostgresResolutionEventHandler
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.models import VoteChoice
from dom_domych.domain.polls.policy import InitiativeOutcome, demo_initiative_policy
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.initiative_cases import PostgresInitiativeCases
from dom_domych.infrastructure.postgres.initiative_followup import (
    PostgresCurrentDeliveryRights,
    PostgresInitiativeFollowupRepository,
)
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    OutboxDeliveryRow,
    ResidentRow,
    ScheduledJobRow,
)
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_followup_models import (
    InitiativeDecisionRow,
    InitiativeReminderRow,
)
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


@dataclass(frozen=True)
class Context:
    house_id: UUID
    actor_id: UUID


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


@pytest.mark.asyncio
async def test_reminders_are_addressed_bounded_and_decision_is_published_once() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z08 requires a dedicated migrated PostgreSQL test database")
    clock = Clock()
    case_id = uuid4()
    author_id = synthetic_id("resident-2")
    context = Context(HOUSE_ONE, author_id)
    chat_id = f"-{str(uuid4().int)[:18]}"
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=chat_id)
            )
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="initiative",
                    title="Велопарковка",
                    description="Тест",
                    status="collecting",
                    version=1,
                    created_at=clock.now(),
                )
            )
            await session.flush()
            session.add(
                CaseMessageRow(
                    case_id=case_id,
                    house_id=HOUSE_ONE,
                    message_id=uuid4(),
                    actor_id=author_id,
                    relation="origin",
                    linked_at=clock.now(),
                )
            )
            audience = await AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                context,
                operation_key=f"z08:audience:{case_id}",
            )
            first, second = [member for member in audience.members if member.reachable_at_snapshot][
                :2
            ]
            for member in (first, second):
                await session.execute(
                    update(ResidentRow)
                    .where(ResidentRow.id == member.resident_id)
                    .values(max_user_id=str(uuid4().int)[:17])
                )
        initiative = InitiativeService(
            PostgresInitiativeCases(sessions), PostgresInitiativeRepository(sessions), clock
        )
        state = await initiative.create(
            case_id,
            "Велопарковка у второго подъезда",
            audience,
            demo_initiative_policy(),
            timedelta(hours=3),
            context,
            operation_key=f"z08:create:{case_id}",
        )
        poll_id = state.current.poll_id
        async with sessions() as session:
            reminder_jobs = (
                await session.scalars(
                    select(ScheduledJobRow)
                    .where(
                        ScheduledJobRow.house_id == HOUSE_ONE,
                        ScheduledJobRow.event_name == EventName.INITIATIVE_REMINDER_DUE.value,
                        ScheduledJobRow.entity_id == poll_id,
                    )
                    .order_by(ScheduledJobRow.due_at)
                )
            ).all()
            assert len(reminder_jobs) == 2
            assert reminder_jobs[0].due_at == clock.now() + timedelta(hours=1)
        async with sessions.begin() as session:
            await PostgresPollRepository(session).record_answer_atomic(
                poll_id,
                HOUSE_ONE,
                first.resident_id,
                VoteChoice.YES,
                uuid4(),
                clock.now() + timedelta(minutes=1),
            )
        followup = InitiativeFollowupService(
            PostgresInitiativeFollowupRepository(sessions, clock),
            PostgresCurrentDeliveryRights(sessions, clock),
            clock,
        )
        clock.current += timedelta(hours=1)
        reminder_event = EventEnvelope(
            event_id=reminder_jobs[0].id,
            source=EventSource.SCHEDULER,
            source_key=f"job:{reminder_jobs[0].id}",
            name=EventName.INITIATIVE_REMINDER_DUE,
            occurred_at=reminder_jobs[0].due_at,
            received_at=clock.now(),
            correlation_id=reminder_jobs[0].id,
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(entity_id=poll_id, entity_version=1),
        )
        handler = PostgresResolutionEventHandler(sessions, clock)
        assert await handler.handle_initiative_reminder(reminder_event)
        assert await handler.handle_initiative_reminder(reminder_event)

        async def plan(key: str) -> tuple[UUID, ...]:
            async with sessions() as session:
                poll = await PostgresPollRepository(session).get_state(poll_id, HOUSE_ONE)
                assert poll is not None
            return await followup.plan_reminders(
                state, poll, demo_reminder_policy(), operation_key=f"z08:{case_id}:{key}"
            )

        assert await plan("first") == ()
        assert await plan("first") == ()
        clock.current += timedelta(minutes=10)
        assert await plan("too-soon") == ()
        clock.current += timedelta(minutes=21)
        assert await plan("second") == (second.resident_id,)
        clock.current += timedelta(minutes=31)
        assert await plan("capped") == ()
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(InitiativeReminderRow)
                    .where(InitiativeReminderRow.poll_id == poll_id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxDeliveryRow)
                    .where(
                        OutboxDeliveryRow.house_id == HOUSE_ONE,
                        OutboxDeliveryRow.recipient_id == second.resident_id,
                        OutboxDeliveryRow.operation_key.like(f"initiative:reminder:{poll_id}:%"),
                    )
                )
                == 2
            )
        async with sessions.begin() as session:
            repository = PostgresPollRepository(session)
            for member in audience.members:
                if member.resident_id == first.resident_id:
                    continue
                await repository.record_answer_atomic(
                    poll_id,
                    HOUSE_ONE,
                    member.resident_id,
                    VoteChoice.YES,
                    uuid4(),
                    clock.now(),
                )
            clock.current = datetime(2026, 9, 27, 12, tzinfo=UTC)
            finalized = await repository.finalize_atomic(poll_id, HOUSE_ONE, clock.now())
            assert finalized.state.outcome == InitiativeOutcome.SUPPORTED
        event_id = uuid4()
        expired = EventEnvelope(
            event_id=event_id,
            source=EventSource.DOMAIN,
            source_key=f"z08:expired:{event_id}",
            name=EventName.POLL_EXPIRED,
            occurred_at=clock.now(),
            received_at=clock.now(),
            correlation_id=event_id,
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(
                entity_id=poll_id,
                entity_version=finalized.state.version,
                case_id=case_id,
            ),
        )
        handler = PostgresResolutionEventHandler(sessions, clock)
        assert await handler.handle_poll_expired(expired) is False
        assert await handler.handle_poll_expired(expired) is False
        async with sessions() as session:
            assert await session.get(InitiativeDecisionRow, poll_id) is not None
            decided_case = await session.get(CaseRow, case_id)
            assert decided_case is not None
            assert decided_case.status == "request_ready" and decided_case.version == 2
            public = await session.scalar(
                select(OutboxDeliveryRow).where(
                    OutboxDeliveryRow.operation_key == f"initiative:decision:{poll_id}"
                )
            )
            assert public is not None
            assert "поддержана по демонстрационному правилу" in public.text
            assert "не протокол ОСС" in public.text
        async with sessions.begin() as session:
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id.in_((first.resident_id, second.resident_id)))
                .values(max_user_id=None)
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )
