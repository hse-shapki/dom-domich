"""Реальные PostgreSQL проверки A02; запускаются с TEST_DATABASE_URL."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from dom_domych.infrastructure.postgres.models import (
    ApartmentRiserRow,
    ApartmentRow,
    HouseRow,
    ResidencyRow,
)
from dom_domych.infrastructure.postgres.session import SqlUnitOfWork, database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_house_links_are_enforced() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
        async with sessions.begin() as session:
            await seed_demo_house(session)
            count = await session.scalar(select(func.count()).select_from(ResidencyRow))
            assert count == 20
            assert await session.scalar(select(func.count()).select_from(HouseRow)) == 2

        async with sessions() as session:
            wrong_house_apartment = await session.scalar(
                select(ApartmentRow.id).where(ApartmentRow.house_id == HOUSE_TWO).limit(1)
            )
            riser = await session.scalar(
                select(ApartmentRiserRow.riser_id)
                .where(ApartmentRiserRow.house_id == HOUSE_ONE)
                .limit(1)
            )
        assert wrong_house_apartment is not None
        assert riser is not None
        async with sessions() as session:
            session.add(
                ApartmentRiserRow(
                    house_id=HOUSE_ONE, apartment_id=wrong_house_apartment, riser_id=riser
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()


@pytest.mark.asyncio
async def test_unit_of_work_uses_new_session_and_rolls_back_uncommitted() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    async with database_lifespan(database_url) as sessions:
        assert isinstance(sessions, async_sessionmaker)
        new_id = uuid4()
        async with SqlUnitOfWork(sessions) as first:
            assert first.session is not None
            first_session = first.session
            first.session.add(
                HouseRow(id=new_id, address="Тест rollback", timezone="Europe/Moscow", demo=True)
            )
        async with SqlUnitOfWork(sessions) as second:
            assert second.session is not None
            assert first_session is not second.session
            assert await second.session.get(HouseRow, new_id) is None
