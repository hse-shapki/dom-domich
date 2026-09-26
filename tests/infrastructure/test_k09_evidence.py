"""Evidence ref остаётся в деле и не создаёт публичное сообщение."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from dom_domych.agent.contracts import CaseCreate, CaseKind, TrustedContext
from dom_domych.application.cases.evidence import EvidenceInput, EvidenceService
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.infrastructure.postgres.case_evidence import PostgresEvidenceWriter
from dom_domych.infrastructure.postgres.case_models import (
    CaseEventRow,
    CaseEvidenceRow,
    CaseMessageRow,
    CaseOperationRow,
    CaseRow,
)
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    InboxEventRow,
    OutboxDeliveryRow,
    ResidentRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 26, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_evidence_is_versioned_idempotent_and_private() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, actor_id = uuid4(), uuid4()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(HouseRow(id=house_id, address="K09 дом", timezone="UTC", demo=True))
            session.add(
                ResidentRow(id=actor_id, display_name="Житель K09", active_house_id=house_id)
            )
        try:
            context = TrustedContext(
                run_id=uuid4(),
                event_id=uuid4(),
                house_id=house_id,
                actor_id=actor_id,
                principal_type=PrincipalType.RESIDENT,
                capabilities=frozenset({"case.write", "evidence.write"}),
                correlation_id=uuid4(),
                mode=ExecutionMode.DEMO,
            )
            case = await PostgresCaseWriter(sessions).create_case(
                CaseCreate(
                    kind=CaseKind.PROBLEM,
                    title="Не горит лампа",
                    description="Не горит лампа на лестнице",
                    entrance=1,
                    object_name="лампа",
                    source_message_id=context.event_id,
                    operation_id=uuid4(),
                ),
                context,
                FixedClock().now(),
            )
            evidence_context = context.model_copy(update={"event_id": uuid4()})
            command = EvidenceInput(case.case_id, case.version, uuid4(), uuid4())
            service = EvidenceService(PostgresEvidenceWriter(sessions), FixedClock())
            updated = await service.add(command, evidence_context)
            assert updated.version == 2
            assert await service.add(command, evidence_context) == updated
            async with sessions() as session:
                evidence = await session.scalar(
                    select(CaseEvidenceRow).where(CaseEvidenceRow.case_id == case.case_id)
                )
                assert evidence is not None
                assert evidence.source_ref == f"event:{evidence_context.event_id}"
                assert evidence.assessment == "pending"
                domain_event = await session.scalar(
                    select(InboxEventRow).where(
                        InboxEventRow.source == "domain",
                        InboxEventRow.source_key == f"evidence-added:{command.operation_id}",
                    )
                )
                assert domain_event is not None and domain_event.status == "pending"
                assert domain_event.normalized_event is not None
                assert domain_event.normalized_event["entity"]["case_id"] == str(case.case_id)
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxDeliveryRow)
                        .where(OutboxDeliveryRow.house_id == house_id)
                    )
                    == 0
                )
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(InboxEventRow).where(
                        InboxEventRow.source == "domain",
                        InboxEventRow.source_key == f"evidence-added:{command.operation_id}",
                    )
                )
                await session.execute(
                    delete(CaseOperationRow).where(CaseOperationRow.house_id == house_id)
                )
                await session.execute(delete(CaseEventRow).where(CaseEventRow.house_id == house_id))
                await session.execute(
                    delete(CaseEvidenceRow).where(CaseEvidenceRow.house_id == house_id)
                )
                await session.execute(
                    delete(CaseMessageRow).where(CaseMessageRow.house_id == house_id)
                )
                await session.execute(delete(CaseRow).where(CaseRow.house_id == house_id))
                await session.execute(delete(ResidentRow).where(ResidentRow.id == actor_id))
                await session.execute(delete(HouseRow).where(HouseRow.id == house_id))
