"""Z06: редакция инициативы заменяет poll и отзывает старые действия атомарно."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.initiatives.service import InitiativeService
from dom_domych.application.polls.callback import StoredPollAction
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.initiatives.models import InitiativeConflict
from dom_domych.domain.polls.models import PollStatus, VoteChoice
from dom_domych.domain.polls.policy import demo_initiative_policy
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.initiative_cases import PostgresInitiativeCases
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.models import OutboxDeliveryRow
from dom_domych.infrastructure.postgres.original_audience import original_audience_id, original_poll
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


@dataclass(frozen=True)
class Context:
    house_id: UUID
    actor_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_initiative_revision_resets_votes_and_revokes_old_token() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z06 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    author_id = synthetic_id("resident-2")
    case_id = uuid4()
    context = Context(HOUSE_ONE, author_id)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="initiative",
                    title="Велопарковка",
                    description="Новая площадка",
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
                operation_key=f"z06:audience:{case_id}",
            )
        service = InitiativeService(
            PostgresInitiativeCases(sessions), PostgresInitiativeRepository(sessions), clock
        )
        original = await service.create(
            case_id,
            "Велопарковка у второго подъезда",
            audience,
            demo_initiative_policy(),
            timedelta(days=2),
            context,
            operation_key=f"z06:create:{case_id}",
        )
        assert (
            await service.create(
                case_id,
                "Велопарковка у второго подъезда",
                audience,
                demo_initiative_policy(),
                timedelta(days=2),
                context,
                operation_key=f"z06:create:{case_id}",
            )
            == original
        )
        async with sessions.begin() as session:
            token = await PostgresPollActionStore(session).create(
                StoredPollAction(
                    poll_id=original.current.poll_id,
                    house_id=HOUSE_ONE,
                    audience_id=audience.audience_id,
                    subject_revision=1,
                    choice=VoteChoice.YES,
                    expires_at=clock.now() + timedelta(days=2),
                    bound_resident_id=author_id,
                )
            )
            await PostgresPollRepository(session).record_answer_atomic(
                original.current.poll_id,
                HOUSE_ONE,
                author_id,
                VoteChoice.YES,
                uuid4(),
                clock.now() + timedelta(minutes=1),
            )
        revised = await service.revise(
            case_id,
            "Велопарковка на шесть мест",
            audience,
            demo_initiative_policy(),
            timedelta(days=2),
            context,
            expected_revision=1,
            operation_key=f"z06:revise:{case_id}",
        )
        assert revised.current.revision == 2
        assert revised.current.poll_id != original.current.poll_id
        assert (
            await service.revise(
                case_id,
                "Велопарковка на шесть мест",
                audience,
                demo_initiative_policy(),
                timedelta(days=2),
                context,
                expected_revision=1,
                operation_key=f"z06:revise:{case_id}",
            )
            == revised
        )
        async with sessions() as session:
            actions = PostgresPollActionStore(session)
            stored_action = await actions.get(token)
            assert stored_action is not None and stored_action.revoked is True
            old_poll = await PostgresPollRepository(session).get_state(
                original.current.poll_id, HOUSE_ONE
            )
            new_poll = await PostgresPollRepository(session).get_state(
                revised.current.poll_id, HOUSE_ONE
            )
            old_notices = (
                await session.scalars(
                    select(OutboxDeliveryRow).where(
                        OutboxDeliveryRow.operation_key.like(
                            f"poll:invite:{original.current.poll_id}:%"
                        )
                    )
                )
            ).all()
            assert len(old_notices) == audience.eligible_count
            assert all(notice.status == "superseded" for notice in old_notices)
            assert old_poll is not None and old_poll.status == PollStatus.CANCELLED
            assert old_poll.tally.yes == 1
            assert new_poll is not None and new_poll.tally.yes == 0
            case = await session.get(CaseRow, case_id)
            assert case is not None
            effective = await original_poll(session, case)
            assert effective is not None and effective.id == revised.current.poll_id
            assert await original_audience_id(session, case) == revised.current.audience_id
            assert await PostgresInitiativeRepository(sessions).get(case_id, HOUSE_ONE) == revised


@pytest.mark.asyncio
async def test_concurrent_revisions_leave_one_active_poll() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z06 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    author_id = synthetic_id("resident-2")
    case_id = uuid4()
    context = Context(HOUSE_ONE, author_id)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="initiative",
                    title="Двор",
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
                operation_key=f"z06:audience:{case_id}",
            )
        service = InitiativeService(
            PostgresInitiativeCases(sessions), PostgresInitiativeRepository(sessions), clock
        )
        await service.create(
            case_id,
            "Озеленение двора",
            audience,
            demo_initiative_policy(),
            timedelta(days=2),
            context,
            operation_key=f"z06:create:{case_id}",
        )

        async def revise(wording: str) -> object:
            return await service.revise(
                case_id,
                wording,
                audience,
                demo_initiative_policy(),
                timedelta(days=2),
                context,
                expected_revision=1,
                operation_key=f"z06:{case_id}:{wording}",
            )

        outcomes = await asyncio.gather(
            revise("Добавить деревья"), revise("Добавить клумбы"), return_exceptions=True
        )
        assert sum(isinstance(value, InitiativeConflict) for value in outcomes) == 1
        state = await PostgresInitiativeRepository(sessions).get(case_id, HOUSE_ONE)
        assert state.current.revision == 2
        async with sessions() as session:
            old = await PostgresPollRepository(session).get_state(
                state.revisions[0].poll_id, HOUSE_ONE
            )
            new = await PostgresPollRepository(session).get_state(state.current.poll_id, HOUSE_ONE)
            assert old is not None and old.status == PollStatus.CANCELLED
            assert new is not None and new.status == PollStatus.OPEN
