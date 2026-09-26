"""Срочная просьба о фото попадает только в личный outbox."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.infrastructure.postgres.emergency_evidence import PostgresEmergencyEvidenceQueue
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, ResidentRow
from dom_domych.infrastructure.postgres.session import database_lifespan


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 26, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_emergency_evidence_goes_to_actor_dm_once() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, actor_id = uuid4(), uuid4()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(HouseRow(id=house_id, address="K11 дом", timezone="UTC", demo=True))
            session.add(
                ResidentRow(id=actor_id, display_name="Житель K11", active_house_id=house_id)
            )
        try:
            context = TrustedContext(
                run_id=uuid4(),
                event_id=uuid4(),
                house_id=house_id,
                actor_id=actor_id,
                principal_type=PrincipalType.RESIDENT,
                capabilities=frozenset({"emergency.handle"}),
                correlation_id=uuid4(),
                mode=ExecutionMode.DEMO,
            )
            queue = PostgresEmergencyEvidenceQueue(sessions, FixedClock())
            case_id = uuid4()
            first = await queue.queue_private(case_id, context, "k11:evidence:once")
            assert await queue.queue_private(case_id, context, "k11:evidence:once") == first
            async with sessions() as session:
                row = await session.scalar(
                    select(OutboxDeliveryRow).where(OutboxDeliveryRow.id == first)
                )
                assert row is not None and row.recipient_id == actor_id
                assert row.chat_id is None and row.status == "pending"
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(OutboxDeliveryRow).where(OutboxDeliveryRow.house_id == house_id)
                )
                await session.execute(delete(ResidentRow).where(ResidentRow.id == actor_id))
                await session.execute(delete(HouseRow).where(HouseRow.id == house_id))
