"""Z03: снимок и его история сохраняются в настоящей PostgreSQL."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from dom_domych.application.audiences.service import AudienceService
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, RISER_E2_A


@dataclass(frozen=True)
class Context:
    house_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_audience_snapshot_survives_restart_and_preserves_denominator() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z03 requires a dedicated migrated PostgreSQL test database")
    key = f"z03:{uuid4()}"
    clock = FixedClock()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            service = AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            )
            first = await service.resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                Context(HOUSE_ONE),
                operation_key=key,
            )
            assert first.eligible_count == 12
            assert first.reachable_count == 11
        async with sessions.begin() as session:
            repository = PostgresAudienceRepository(session)
            loaded = await repository.get_scoped(first.audience_id, HOUSE_ONE)
            assert loaded == first
            assert await repository.get_scoped(first.audience_id, HOUSE_TWO) is None
            service = AudienceService(PostgresHouseContext(session, clock), repository, clock)
            repeated = await service.resolve(first.scope, Context(HOUSE_ONE), operation_key=key)
            assert repeated == first
            changed = await service.resolve(
                AudienceScope(ScopeKind.RISER, riser_id=RISER_E2_A, riser_kind="cold_water"),
                Context(HOUSE_ONE),
                operation_key=f"{key}:revised",
                supersedes_id=first.audience_id,
            )
            assert changed.criteria_revision == 2
            assert changed.eligible_count == 6
            assert (await repository.get(first.audience_id)) == first


@pytest.mark.asyncio
async def test_audience_successor_and_operation_key_are_unique_under_concurrency() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z03 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    key = f"z03:{uuid4()}"
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            service = AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            )
            first = await service.resolve(
                AudienceScope(ScopeKind.HOUSE), Context(HOUSE_ONE), operation_key=key
            )

        async def revise(parent_id: UUID, kind: ScopeKind) -> object:
            async with sessions.begin() as session:
                service = AudienceService(
                    PostgresHouseContext(session, clock),
                    PostgresAudienceRepository(session),
                    clock,
                )
                scope = AudienceScope(
                    kind, entrance=2, floor=5 if kind == ScopeKind.FLOOR else None
                )
                return await service.resolve(
                    scope,
                    Context(HOUSE_ONE),
                    operation_key=f"{key}:{parent_id}:{kind}",
                    supersedes_id=parent_id,
                )

        outcomes = await asyncio.gather(
            revise(first.audience_id, ScopeKind.ENTRANCE),
            revise(first.audience_id, ScopeKind.ENTRANCE),
            return_exceptions=True,
        )
        assert outcomes[0] == outcomes[1]
        async with sessions.begin() as session:
            service = AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            )
            with pytest.raises(ValueError, match="already superseded"):
                await service.resolve(
                    AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                    Context(HOUSE_ONE),
                    operation_key=f"{key}:different",
                    supersedes_id=first.audience_id,
                )

        async with sessions.begin() as session:
            service = AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            )
            another_root = await service.resolve(
                AudienceScope(ScopeKind.HOUSE),
                Context(HOUSE_ONE),
                operation_key=f"{key}:root-two",
            )
        competing = await asyncio.gather(
            revise(another_root.audience_id, ScopeKind.ENTRANCE),
            revise(another_root.audience_id, ScopeKind.FLOOR),
            return_exceptions=True,
        )
        assert sum(isinstance(result, ValueError) for result in competing) == 1
