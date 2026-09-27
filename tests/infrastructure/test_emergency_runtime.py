"""A14/K11: авария фиксирует аудиторию без ожидания коллективного poll."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from dom_domych.agent.contracts import CaseCreate, CaseKind
from dom_domych.application.documents.production import RequestDocumentEventHandler
from dom_domych.application.jobs.inbox_worker import EventDispatcher, InboxWorker
from dom_domych.application.requests.emergency_runtime import (
    EmergencyAudienceEventHandler,
    emergency_audience_key,
)
from dom_domych.contracts.base import ExecutionMode, PrincipalType, TrustedContext
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import InboxEventRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.requests import PostgresRequestCases
from dom_domych.infrastructure.postgres.resolution import PostgresResolutionCasePort
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_audience_models import (
    AudienceMemberRow,
    AudienceSnapshotRow,
)
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 28, 8, tzinfo=UTC)


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("emergency runtime requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_emergency_freezes_audience_for_resolution_and_appeal() -> None:
    clock = FixedClock()
    actor_id = synthetic_id("resident-2")
    context = TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=HOUSE_ONE,
        actor_id=actor_id,
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset({"case.write"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )
    command = CaseCreate(
        kind=CaseKind.EMERGENCY,
        title=f"Аварийная течь {uuid4()}",
        description="Сильная течь на пятом этаже второго подъезда",
        entrance=2,
        floor=5,
        object_name="cold_water",
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
        case = await PostgresCaseWriter(sessions, emit_workflow_events=True).create_case(
            command, context, clock.now()
        )
        dispatcher = EventDispatcher(
            {EventName.EMERGENCY_DETECTED: EmergencyAudienceEventHandler(sessions, clock)}
        )
        worker = InboxWorker(sessions, dispatcher, clock, "emergency-runtime")
        assert await worker.run_once()

        async with sessions() as session:
            audience = await session.scalar(
                select(AudienceSnapshotRow).where(
                    AudienceSnapshotRow.operation_key == emergency_audience_key(case.case_id)
                )
            )
            assert audience is not None
            assert audience.scope_kind == "floor" and audience.entrance == 2
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AudienceMemberRow)
                    .where(AudienceMemberRow.audience_id == audience.id)
                )
                > 0
            )
            detected = await session.scalar(
                select(InboxEventRow).where(
                    InboxEventRow.source_key == f"emergency-detected:{case.case_id}"
                )
            )
            assert detected is not None and detected.status == "done"

        request_id, draft_id, source_id, rule_id, responsible_id = (uuid4() for _ in range(5))
        executor_operation_id = uuid4()
        async with sessions.begin() as session:
            case_row = await session.get(CaseRow, case.case_id)
            assert case_row is not None
            case_row.status = "in_progress"
            case_row.version = 2
            session.add(
                KnowledgeSourceRow(
                    source_id=source_id,
                    revision=1,
                    house_id=HOUSE_ONE,
                    title="Демо-правило аварии",
                    uri="https://example.invalid/emergency-runtime",
                    text="Синтетическое проверенное правило",
                    reviewed=True,
                )
            )
            await session.flush()
            session.add(
                RuleVersionRow(
                    id=rule_id,
                    source_id=source_id,
                    source_revision=1,
                    house_id=HOUSE_ONE,
                    topic="cold_water",
                    responsible_id=responsible_id,
                )
            )
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=HOUSE_ONE,
                    case_id=case.case_id,
                    draft_id=draft_id,
                    draft_version=1,
                    content_sha256="b" * 64,
                    responsible_id=responsible_id,
                    rule_id=rule_id,
                    source_refs=[f"{source_id}:1"],
                    status="registered",
                    approved_version=1,
                    approval_actor=actor_id,
                    executor_operation_id=executor_operation_id,
                    registration_id="DEMO-EMERGENCY-1",
                    registered_at=clock.now(),
                    external_status="registered",
                    external_version=1,
                )
            )

        resolution_case = await PostgresResolutionCasePort(sessions).get_for_resolution(
            case.case_id, HOUSE_ONE
        )
        assert resolution_case.original_audience_id == audience.id
        assert await PostgresRequestCases(sessions).get_for_request(case.case_id, HOUSE_ONE)

        registration = EventEnvelope(
            event_id=uuid4(),
            source=EventSource.DOMAIN,
            source_key=f"request-registered:{request_id}",
            name=EventName.REQUEST_REGISTERED,
            occurred_at=clock.now(),
            received_at=clock.now(),
            correlation_id=executor_operation_id,
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(
                entity_id=request_id,
                entity_version=2,
                case_id=case.case_id,
            ),
        )
        assert await RequestDocumentEventHandler(sessions, clock)(registration) is False
        async with sessions.begin() as session:
            document = await session.scalar(
                select(DocumentRow).where(DocumentRow.request_id == request_id)
            )
            assert document is not None
            assert document.poll_id is None and document.audience_id == audience.id
            # Не оставляем queued запись соседнему document worker test.
            document.status = "failed"
