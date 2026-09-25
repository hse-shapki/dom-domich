"""A05: реальные выборки реестра на PostgreSQL, включая изоляцию домов."""

import os
from datetime import UTC, datetime

import pytest

from dom_domych.application.audiences.service import AudienceService
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.ports.core import HouseContextPort
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.domain.test_audience_service import FakeAudienceRepository, FakeContext
from tests.fixtures.zamira_house import (
    HOUSE_ONE,
    HOUSE_TWO,
    RISER_E2_A,
    RISER_E2_B,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_house_scope_floor_riser_and_unique_residents() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
        async with sessions() as session:
            port: HouseContextPort = PostgresHouseContext(session, FixedClock())
            rows = await port.list_house_residencies(HOUSE_ONE)
            eligible = [row for row in rows if row.confirmed and row.adult and row.active]
            floor = AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5)
            floor_residents = {row.resident_id for row in eligible if floor.matches(row)}
            assert len(floor_residents) == 12
            first_riser = AudienceScope(
                kind=ScopeKind.RISER, riser_id=RISER_E2_A, riser_kind="cold_water"
            )
            second_riser = AudienceScope(
                kind=ScopeKind.RISER, riser_id=RISER_E2_B, riser_kind="cold_water"
            )
            assert len({row.resident_id for row in eligible if first_riser.matches(row)}) == 6
            assert len({row.resident_id for row in eligible if second_riser.matches(row)}) == 8
            assert len(await port.list_house_residencies(HOUSE_TWO)) == 1
            assert not any(row.house_id == HOUSE_TWO for row in rows)
            assert await port.house_for_chat("unbound-chat") is None
            assert await port.resident_for_max_user("unbound-user") is None


@pytest.mark.asyncio
async def test_audience_service_uses_postgres_residencies_without_changing_denominator() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
        async with sessions() as session:
            service = AudienceService(
                PostgresHouseContext(session, FixedClock()),
                FakeAudienceRepository(),
                FixedClock(),
            )
            audience = await service.resolve(
                AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5),
                FakeContext(HOUSE_ONE),
                operation_key="a05:floor-five",
            )
            assert audience.eligible_count == 12
            assert audience.reachable_count == 11
