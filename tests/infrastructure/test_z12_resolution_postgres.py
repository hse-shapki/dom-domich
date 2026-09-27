"""Z12/13: trusted done, исходная аудитория и три результата на PostgreSQL."""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.polls.service import PollService
from dom_domych.application.resolution.production import PostgresResolutionEventHandler
from dom_domych.application.resolution.service import ResolutionService
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.polls.policy import demo_problem_policy, demo_resolution_policy
from dom_domych.domain.resolution.models import (
    ResolutionConflict,
    ResolutionState,
    ResolutionStatus,
)
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import (
    InboxEventRow,
    OutboxDeliveryRow,
    ScheduledJobRow,
)
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.resolution import (
    PostgresResolutionCasePort,
    PostgresResolutionStore,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_executor_models import DemoExecutorRow
from dom_domych.infrastructure.postgres.z_resolution_models import ResolutionCheckRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO


@dataclass(frozen=True)
class Context:
    house_id: UUID
    capabilities: frozenset[str] = frozenset()


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 14, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("yes", "no", "expected"),
    [
        (7, 0, ResolutionStatus.CLOSED),
        (5, 2, ResolutionStatus.REOPENED),
        (1, 0, ResolutionStatus.UNCONFIRMED),
    ],
)
async def test_resolution_outcome_is_atomic_and_uses_original_audience(
    yes: int, no: int, expected: ResolutionStatus
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z12/13 requires a dedicated migrated PostgreSQL test database")
    clock = Clock()
    case_id, request_id, draft_id, rule_id, source_id, executor_id, done_id = (
        uuid4() for _ in range(7)
    )
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            session.add_all(
                [
                    CaseRow(
                        id=case_id,
                        house_id=HOUSE_ONE,
                        kind="problem",
                        title="Проверка результата",
                        description="Синтетическое дело",
                        status="in_progress",
                        version=3,
                        created_at=clock.now(),
                    ),
                    KnowledgeSourceRow(
                        source_id=source_id,
                        revision=1,
                        house_id=HOUSE_ONE,
                        title="Демо-правило",
                        uri="https://example.invalid/demo",
                        text="Только тест",
                        reviewed=True,
                    ),
                    RuleVersionRow(
                        id=rule_id,
                        source_id=source_id,
                        source_revision=1,
                        house_id=HOUSE_ONE,
                        topic="maintenance",
                        responsible_id=uuid4(),
                    ),
                ]
            )
            audience = await AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                Context(HOUSE_ONE),
                operation_key=f"z12:audience:{case_id}",
            )
            await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.PROBLEM_CONFIRMATION,
                demo_problem_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z12:original:{case_id}",
            )
            await session.flush()
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=HOUSE_ONE,
                    case_id=case_id,
                    draft_id=draft_id,
                    draft_version=1,
                    content_sha256="a" * 64,
                    responsible_id=uuid4(),
                    rule_id=rule_id,
                    source_refs=["demo:1"],
                    status="registered",
                    approved_version=1,
                    approval_actor=audience.members[0].resident_id,
                    executor_operation_id=executor_id,
                    registration_id="DEMO-TEST",
                    registered_at=clock.now() - timedelta(hours=1),
                    external_status="done",
                    external_version=2,
                )
            )
            await session.flush()
            session.add(
                DemoExecutorRow(
                    id=executor_id,
                    house_id=HOUSE_ONE,
                    request_id=request_id,
                    operation_key=f"z12:executor:{case_id}",
                    draft_id=draft_id,
                    draft_revision=1,
                    content_sha256="a" * 64,
                    status="done",
                    submitted_at=clock.now() - timedelta(hours=2),
                    registration_number="DEMO-TEST",
                    registered_at=clock.now() - timedelta(hours=1),
                    status_updated_at=clock.now(),
                    processed_event_ids=[str(done_id)],
                )
            )
        operation = await PostgresDemoExecutor(sessions, clock).get(HOUSE_ONE, request_id)
        service = ResolutionService(
            PostgresResolutionCasePort(sessions), PostgresResolutionStore(sessions, clock), clock
        )
        worker = Context(
            HOUSE_ONE,
            frozenset({"resolution.start_from_executor", "resolution.finalize"}),
        )
        events = PostgresResolutionEventHandler(sessions, clock)
        done_event = EventEnvelope(
            event_id=done_id,
            source=EventSource.EXECUTOR,
            source_key=f"executor:request.status_changed:{done_id}",
            name=EventName.REQUEST_STATUS_CHANGED,
            occurred_at=clock.now(),
            received_at=clock.now(),
            correlation_id=executor_id,
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(entity_id=request_id, entity_version=2, case_id=case_id),
        )
        assert await events.handle_status(done_event) is False
        async with sessions() as session:
            check = await session.scalar(
                select(ResolutionCheckRow).where(ResolutionCheckRow.done_event_id == done_id)
            )
            assert check is not None
            state = ResolutionState(
                check_id=check.id,
                case_id=check.case_id,
                house_id=check.house_id,
                request_id=check.request_id,
                original_audience_id=check.original_audience_id,
                poll_id=check.poll_id,
                case_version_at_start=check.case_version_at_start,
                done_event_id=check.done_event_id,
                started_at=check.started_at,
            )
        assert state.original_audience_id == audience.audience_id
        assert (
            await service.start_check(
                case_id,
                operation,
                done_id,
                audience,
                demo_resolution_policy(),
                timedelta(hours=2),
                worker,
                operation_key=f"z12:start:{case_id}",
            )
            == state
        )
        async with sessions() as session:
            case = await session.get(CaseRow, case_id)
            assert case is not None and case.status == "checking_resolution"
            assert case.closed_at is None
            poll = await PostgresPollRepository(session).get_state(state.poll_id, HOUSE_ONE)
            assert poll is not None and poll.tally.eligible == 12
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxDeliveryRow)
                    .where(
                        OutboxDeliveryRow.operation_key.like(f"resolution:check:{state.poll_id}:%")
                    )
                )
                == 12
            )
        for index, member in enumerate(audience.members[: yes + no]):
            async with sessions.begin() as session:
                await PostgresPollRepository(session).record_answer_atomic(
                    state.poll_id,
                    HOUSE_ONE,
                    member.resident_id,
                    VoteChoice.YES if index < yes else VoteChoice.NO,
                    uuid4(),
                    clock.now() + timedelta(minutes=1),
                )
        clock.current += timedelta(hours=2)
        events = PostgresResolutionEventHandler(sessions, clock)
        scheduled = EventEnvelope(
            event_id=uuid4(),
            source=EventSource.SCHEDULER,
            source_key=f"job:test:{state.poll_id}",
            name=EventName.POLL_EXPIRED,
            occurred_at=clock.now(),
            received_at=clock.now(),
            correlation_id=state.poll_id,
            house_id=HOUSE_ONE,
            entity=EntityEventPayload(entity_id=state.poll_id, entity_version=3),
        )
        assert await events.handle_poll_expired(scheduled)
        async with sessions() as session:
            poll = await PostgresPollRepository(session).get_state(state.poll_id, HOUSE_ONE)
            domain_row = await session.scalar(
                select(InboxEventRow).where(
                    InboxEventRow.source_key == f"poll:{state.poll_id}:poll.expired"
                )
            )
            assert poll is not None and domain_row is not None
            assert domain_row.normalized_event is not None
            domain_event = EventEnvelope.model_validate_json(
                json.dumps(domain_row.normalized_event)
            )
        assert await events.handle_poll_expired(domain_event) is False
        result = await service.finalize(state.check_id, poll, worker, operation_key="finish")
        assert result.status is expected
        repeated = await service.finalize(state.check_id, poll, worker, operation_key="finish")
        assert repeated == result
        async with sessions() as session:
            case = await session.get(CaseRow, case_id)
            assert case is not None and case.status == expected.value and case.version == 5
            assert (case.closed_at is not None) == (expected is ResolutionStatus.CLOSED)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(CaseEventRow)
                    .where(CaseEventRow.case_id == case_id)
                )
                == 2
            )
            job = await session.scalar(
                select(ScheduledJobRow).where(ScheduledJobRow.entity_id == state.poll_id)
            )
            assert job is not None and job.status == "skipped_stale"
            check = await session.get(ResolutionCheckRow, state.check_id)
            assert check is not None and check.status == expected.value
            if expected is ResolutionStatus.REOPENED:
                assert (
                    await session.scalar(
                        select(InboxEventRow).where(
                            InboxEventRow.source_key == f"resolution:rejected:{state.check_id}"
                        )
                    )
                    is not None
                )
        with pytest.raises(ResolutionConflict):
            await PostgresResolutionCasePort(sessions).get_for_resolution(case_id, HOUSE_TWO)
