"""Z07: публичная карточка из текущего poll попадает в A outbox."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.cards.production import PostgresPublicCards
from dom_domych.application.initiatives.service import InitiativeService
from dom_domych.application.polls.service import PollService
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.polls.policy import demo_initiative_policy, demo_problem_policy
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.initiative_cases import PostgresInitiativeCases
from dom_domych.infrastructure.postgres.initiatives import PostgresInitiativeRepository
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, PollActionRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


@dataclass(frozen=True)
class Context:
    house_id: UUID


@dataclass(frozen=True)
class AuthorContext:
    house_id: UUID
    actor_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_problem_card_uses_frozen_denominator_and_coalesces_edits() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z07 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    case_id = uuid4()
    chat_id = str(uuid4().int)[:18]
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
                    kind="problem",
                    title="Не горит свет",
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
                operation_key=f"z07:audience:{case_id}",
            )
            poll = await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.PROBLEM_CONFIRMATION,
                demo_problem_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z07:poll:{case_id}",
            )
        cards = PostgresPublicCards(sessions, clock)
        base_id = await cards.publish_problem(poll.definition.poll_id, HOUSE_ONE)
        assert await cards.publish_problem(poll.definition.poll_id, HOUSE_ONE) == base_id
        async with sessions.begin() as session:
            base = await session.get(OutboxDeliveryRow, base_id)
            assert base is not None
            assert "Подтвердили: 0/12" in base.text
            assert "демонстрационная настройка" in base.text
            assert [item["text"] for item in base.buttons] == ["Подтверждаю", "Не подтверждаю"]
            action = await PostgresPollActionStore(session).get(base.buttons[0]["payload"])
            assert action is not None and action.poll_id == poll.definition.poll_id
            assert action.choice is VoteChoice.YES
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PollActionRow)
                    .where(PollActionRow.poll_id == poll.definition.poll_id)
                )
                == 2
            )
            base.status = "sent"
            base.max_message_id = "test-message"
        for member in audience.members[:2]:
            async with sessions.begin() as session:
                await PostgresPollRepository(session).record_answer_atomic(
                    poll.definition.poll_id,
                    HOUSE_ONE,
                    member.resident_id,
                    VoteChoice.YES,
                    uuid4(),
                    clock.now() + timedelta(minutes=1),
                )
            await cards.publish_problem(poll.definition.poll_id, HOUSE_ONE)
        async with sessions() as session:
            rows = (
                await session.scalars(
                    select(OutboxDeliveryRow).where(
                        OutboxDeliveryRow.house_id == HOUSE_ONE,
                        OutboxDeliveryRow.edit_key == f"problem:{case_id}",
                    )
                )
            ).all()
            assert len(rows) == 2
            assert {row.status for row in rows} == {"pending", "superseded"}
            latest = next(row for row in rows if row.status == "pending")
            assert "Подтвердили: 2/12" in latest.text
            assert "resident_id" not in latest.text
            assert latest.buttons == base.buttons
        async with sessions.begin() as session:
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )


@pytest.mark.asyncio
async def test_initiative_card_uses_current_revision_without_personal_answers() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z07 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    case_id = uuid4()
    author_id = synthetic_id("resident-2")
    chat_id = str(uuid4().int)[:18]
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
                    title="Инициатива",
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
                Context(HOUSE_ONE),
                operation_key=f"z07:audience:{case_id}",
            )
        service = InitiativeService(
            PostgresInitiativeCases(sessions), PostgresInitiativeRepository(sessions), clock
        )
        await service.create(
            case_id,
            "Сделать велопарковку",
            audience,
            demo_initiative_policy(),
            timedelta(days=2),
            AuthorContext(HOUSE_ONE, author_id),
            operation_key=f"z07:create:{case_id}",
        )
        delivery_id = await PostgresPublicCards(sessions, clock).publish_initiative(
            case_id, HOUSE_ONE
        )
        async with sessions() as session:
            delivery = await session.get(OutboxDeliveryRow, delivery_id)
            assert delivery is not None
            assert "Участие: 0/12" in delivery.text
            assert "не протокол ОСС" in delivery.text
            assert all(str(member.resident_id) not in delivery.text for member in audience.members)
        async with sessions.begin() as session:
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )
