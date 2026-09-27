"""Z11: регистрация demo executor, права, конкуренция и достоверный outbox."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.domain.executor.models import (
    ApprovedDraft,
    ExecutorConflict,
    ExecutorForbidden,
    ExecutorNotFound,
    ExternalStatus,
)
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.demo_executor import (
    PostgresDemoExecutor,
    PostgresExecutorPort,
)
from dom_domych.infrastructure.postgres.knowledge_models import KnowledgeSourceRow, RuleVersionRow
from dom_domych.infrastructure.postgres.models import InboxEventRow, OutboxDeliveryRow, ResidencyRow
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_executor_models import DemoExecutorRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO


@dataclass(frozen=True)
class Context:
    house_id: UUID
    capabilities: frozenset[str]


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 14, tzinfo=UTC)


@pytest.mark.asyncio
async def test_postgres_demo_executor_is_idempotent_and_emits_trusted_status() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z11 requires a dedicated migrated PostgreSQL test database")
    clock = Clock()
    case_id, request_id, draft_id, rule_id, source_id = (uuid4() for _ in range(5))
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            # В тестовом доме роль оператора получает синтетический подтверждённый житель.
            approval_actor = await session.scalar(
                select(ResidencyRow.resident_id).where(ResidencyRow.house_id == HOUSE_ONE).limit(1)
            )
            assert approval_actor is not None
            session.add_all(
                [
                    CaseRow(
                        id=case_id,
                        house_id=HOUSE_ONE,
                        kind="problem",
                        title="Проверка исполнителя",
                        description="Синтетическое дело",
                        status="preparing_request",
                        version=1,
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
            await session.flush()
            session.add(
                RequestRow(
                    id=request_id,
                    house_id=HOUSE_ONE,
                    case_id=case_id,
                    draft_id=draft_id,
                    draft_version=2,
                    content_sha256="a" * 64,
                    responsible_id=uuid4(),
                    rule_id=rule_id,
                    source_refs=["demo:1"],
                    status="submitting",
                    approved_version=2,
                    approval_actor=approval_actor,
                    external_version=0,
                )
            )
        store = PostgresDemoExecutor(sessions, clock)
        service = DemoExecutorService(store, clock)
        draft = ApprovedDraft(HOUSE_ONE, request_id, draft_id, 2, "a" * 64)
        submit = Context(HOUSE_ONE, frozenset({"demo_executor.submit"}))
        register = Context(HOUSE_ONE, frozenset({"demo_executor.register"}))
        operator = Context(HOUSE_ONE, frozenset({"demo_executor.operator"}))
        resident = Context(HOUSE_ONE, frozenset())
        results = await asyncio.gather(
            service.submit(draft, "same-submit", submit),
            service.submit(draft, "same-submit", submit),
        )
        assert results[0] == results[1]
        operation = results[0]
        with pytest.raises(ExecutorConflict):
            await service.submit(draft, "other-submit", submit)
        with pytest.raises(ExecutorForbidden):
            await service.set_status(operation.operation_id, ExternalStatus.DONE, uuid4(), resident)
        with pytest.raises(ExecutorNotFound):
            await service.get_status(request_id, Context(HOUSE_TWO, operator.capabilities))
        registered, emitted = await service.register(operation.operation_id, register)
        assert emitted and registered.registration_number is not None
        assert (await service.register(operation.operation_id, register))[1] is False
        event_id = uuid4()
        done, emitted = await service.set_status(
            operation.operation_id, ExternalStatus.DONE, event_id, operator
        )
        assert emitted and done.status is ExternalStatus.DONE
        repeated = await service.set_status(
            operation.operation_id, ExternalStatus.DONE, event_id, operator
        )
        assert repeated[1] is False
        ref = await PostgresExecutorPort(store).get_status(request_id, HOUSE_ONE)
        assert ref.external_status == "done" and ref.case_id == case_id
        async with sessions() as session:
            row = await session.get(DemoExecutorRow, operation.operation_id)
            assert row is not None and row.status == "done" and len(row.processed_event_ids) == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DemoExecutorRow)
                    .where(
                        DemoExecutorRow.house_id == HOUSE_ONE,
                        DemoExecutorRow.request_id == request_id,
                    )
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(InboxEventRow)
                    .where(
                        InboxEventRow.house_id == HOUSE_ONE,
                        InboxEventRow.source == "executor",
                        InboxEventRow.source_key.like("executor:%"),
                    )
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboxDeliveryRow)
                    .where(
                        OutboxDeliveryRow.house_id == HOUSE_ONE,
                        OutboxDeliveryRow.operation_key.like(
                            f"executor:notice:{operation.operation_id}:%"
                        ),
                    )
                )
                == 2
            )
