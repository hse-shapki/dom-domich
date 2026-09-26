"""Поиск кандидатов на мигрированной PostgreSQL через TEST_DATABASE_URL."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from dom_domych.agent.contracts import CaseSearch, TrustedContext
from dom_domych.application.cases.candidates import CandidateService
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.infrastructure.postgres.case_candidates import PostgresCaseReader
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.session import database_lifespan


@pytest.mark.asyncio
async def test_candidates_respect_house_location_and_recent_closed() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, other_house = uuid4(), uuid4()
    ids = [uuid4() for _ in range(4)]
    now = datetime.now(UTC)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add_all(
                [
                    HouseRow(id=house_id, address="K07 дом 1", timezone="UTC", demo=True),
                    HouseRow(id=other_house, address="K07 дом 2", timezone="UTC", demo=True),
                ]
            )
        async with sessions.begin() as session:
            for index, case_id in enumerate(ids):
                session.add(
                    CaseRow(
                        id=case_id,
                        house_id=other_house if index == 3 else house_id,
                        kind="problem",
                        title="Темно на лестнице",
                        description="Не горит лампа на лестнице",
                        entrance=2 if index == 1 else 1,
                        floor=3,
                        object_name="лампа",
                        status="closed" if index == 2 else "detected",
                        version=1,
                        created_at=now - timedelta(days=40) if index == 2 else now,
                        closed_at=now - timedelta(days=31) if index == 2 else None,
                        recurrence_of=None,
                        embedding=None,
                        embedding_revision=None,
                    )
                )
        try:
            context = TrustedContext(
                run_id=uuid4(),
                event_id=uuid4(),
                house_id=house_id,
                actor_id=uuid4(),
                principal_type=PrincipalType.RESIDENT,
                capabilities=frozenset({"case.read"}),
                correlation_id=uuid4(),
                mode=ExecutionMode.DEMO,
            )
            service = CandidateService(PostgresCaseReader(sessions))
            found = await service.search(
                CaseSearch(query="не горит лампа", entrance=1, object_name="лампа"),
                context,
                at=now,
            )
            assert [item.case_id for item in found] == [ids[0]]
            assert await service.get(ids[3], context) is None
            assert (await service.get(ids[0], context)).version == 1
        finally:
            async with sessions.begin() as session:
                await session.execute(delete(CaseRow).where(CaseRow.id.in_(ids)))
                await session.execute(
                    delete(HouseRow).where(HouseRow.id.in_([house_id, other_house]))
                )
