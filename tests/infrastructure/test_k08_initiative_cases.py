"""K08/Z06: production case reference не доверяет house/author от вызывающего кода."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.initiative_cases import PostgresInitiativeCases
from dom_domych.infrastructure.postgres.models import HouseRow, ResidentRow
from dom_domych.infrastructure.postgres.session import database_lifespan


@pytest.mark.asyncio
async def test_initiative_case_uses_origin_author_and_hides_other_house() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, other_house, case_id, author_id, event_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add_all(
                [
                    HouseRow(id=house_id, address="K08 инициативы", timezone="UTC", demo=True),
                    HouseRow(id=other_house, address="K08 чужой дом", timezone="UTC", demo=True),
                    ResidentRow(
                        id=author_id,
                        display_name="Автор инициативы",
                        active_house_id=house_id,
                    ),
                ]
            )
            await session.flush()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=house_id,
                    kind="initiative",
                    title="Велопарковка",
                    description="Установить велопарковку у первого подъезда",
                    entrance=1,
                    floor=None,
                    object_name="bike_parking",
                    status="detected",
                    version=3,
                    created_at=now,
                    closed_at=None,
                    recurrence_of=None,
                    embedding=None,
                    embedding_revision=None,
                )
            )
            await session.flush()
            session.add(
                CaseMessageRow(
                    case_id=case_id,
                    house_id=house_id,
                    message_id=event_id,
                    actor_id=author_id,
                    relation="origin",
                    linked_at=now,
                )
            )
        try:
            cases = PostgresInitiativeCases(sessions)
            reference = await cases.get_case(case_id, house_id)

            assert reference.case_id == case_id
            assert reference.house_id == house_id
            assert reference.author_id == author_id
            assert reference.kind == "initiative"
            assert reference.version == 3
            with pytest.raises(ValueError, match="CASE_NOT_FOUND"):
                await cases.get_case(case_id, other_house)
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(CaseMessageRow).where(CaseMessageRow.case_id == case_id)
                )
                await session.execute(delete(CaseRow).where(CaseRow.id == case_id))
                await session.execute(delete(ResidentRow).where(ResidentRow.id == author_id))
                await session.execute(
                    delete(HouseRow).where(HouseRow.id.in_([house_id, other_house]))
                )
