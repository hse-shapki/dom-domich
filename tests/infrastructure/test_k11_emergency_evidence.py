"""Срочная просьба о фото попадает только в личный outbox."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.application.agent.composition import build_k_tool_handlers
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.emergency_evidence import PostgresEmergencyEvidenceQueue
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, ResidentRow
from dom_domych.infrastructure.postgres.session import database_lifespan


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 26, 12, tzinfo=UTC)


class UnusedSubmitter:
    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation:
        raise AssertionError("clarification must not submit a request")


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


@pytest.mark.asyncio
async def test_production_emergency_tool_queues_private_clarification() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, actor_id, case_id = uuid4(), uuid4(), uuid4()
    clock = FixedClock()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(HouseRow(id=house_id, address="K11 tool", timezone="UTC", demo=True))
            session.add(
                ResidentRow(id=actor_id, display_name="Житель K11 tool", active_house_id=house_id)
            )
            await session.flush()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=house_id,
                    kind="emergency",
                    title="Течёт вода",
                    description="Течёт вода, место нужно уточнить",
                    entrance=None,
                    floor=None,
                    object_name="leak",
                    status="detected",
                    version=1,
                    created_at=clock.now(),
                    closed_at=None,
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
                actor_id=actor_id,
                principal_type=PrincipalType.RESIDENT,
                capabilities=frozenset({"emergency.handle", "request.write"}),
                correlation_id=uuid4(),
                mode=ExecutionMode.DEMO,
            )
            handlers = build_k_tool_handlers(sessions, clock, UnusedSubmitter())
            result = await handlers.execute(
                "emergency.handle",
                f'{{"case_id":"{case_id}","expected_case_version":1}}',
                context,
            )

            assert result.ok
            assert result.data is not None and result.data["status"] == "clarify_location"
            async with sessions() as session:
                delivery = await session.scalar(
                    select(OutboxDeliveryRow).where(OutboxDeliveryRow.house_id == house_id)
                )
                assert delivery is not None and delivery.recipient_id == actor_id
                assert delivery.chat_id is None
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(OutboxDeliveryRow).where(OutboxDeliveryRow.house_id == house_id)
                )
                await session.execute(delete(CaseRow).where(CaseRow.id == case_id))
                await session.execute(delete(ResidentRow).where(ResidentRow.id == actor_id))
                await session.execute(delete(HouseRow).where(HouseRow.id == house_id))
