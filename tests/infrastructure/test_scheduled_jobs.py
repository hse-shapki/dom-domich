"""A09: дедлайны в PostgreSQL, idempotency и no-op устаревшей версии."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.jobs.scheduler import JobScheduler
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import JobIntent
from dom_domych.infrastructure.postgres.jobs import (
    DueJob,
    JobConflictError,
    JobLeaseLostError,
    PostgresJobQueue,
)
from dom_domych.infrastructure.postgres.models import ScheduledJobRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


class FakeRevisions:
    def __init__(self, version: int | None) -> None:
        self.version = version

    async def current_version(self, _job: DueJob) -> int | None:
        return self.version


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("A09 requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_deadline_survives_commit_and_dispatches_only_when_due() -> None:
    clock = FixedClock()
    entity_id = uuid4()
    intent = JobIntent(
        HOUSE_ONE,
        f"a09:{uuid4()}",
        EventName.POLL_EXPIRED.value,
        clock.now() + timedelta(minutes=10),
        entity_id,
        3,
    )
    seen: list[EventEnvelope] = []

    async def handle(event: EventEnvelope) -> None:
        seen.append(event)

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            queue = PostgresJobQueue(session)
            job_id = await queue.enqueue(intent)
            assert await queue.enqueue(intent) == job_id
            with pytest.raises(JobConflictError):
                await queue.enqueue(
                    JobIntent(
                        HOUSE_ONE,
                        intent.operation_key,
                        intent.event_name,
                        intent.due_at,
                        entity_id,
                        4,
                    )
                )
        worker = JobScheduler(
            sessions,
            EventDispatcher({EventName.POLL_EXPIRED: handle}),
            FakeRevisions(3),
            clock,
            "scheduler-1",
        )
        assert not await worker.run_once()
        clock.current += timedelta(minutes=10)
        assert await worker.run_once()
        assert not await worker.run_once()
        async with sessions.begin() as session:
            row = await session.get(ScheduledJobRow, job_id)
            assert row is not None and row.status == "done" and row.attempts == 1
            await session.execute(delete(ScheduledJobRow).where(ScheduledJobRow.id == job_id))
    assert len(seen) == 1
    assert seen[0].source is EventSource.SCHEDULER
    assert seen[0].entity is not None and seen[0].entity.entity_id == entity_id


@pytest.mark.asyncio
async def test_changed_version_skips_old_deadline_after_restart() -> None:
    clock = FixedClock()
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            job_id = await PostgresJobQueue(session).enqueue(
                JobIntent(
                    HOUSE_ONE, f"a09:{uuid4()}", EventName.JOB_DUE.value, clock.now(), uuid4(), 2
                )
            )

        async def should_not_run(_event: EventEnvelope) -> None:
            pytest.fail("stale job must not call use case")

        restarted_worker = JobScheduler(
            sessions,
            EventDispatcher({EventName.JOB_DUE: should_not_run}),
            FakeRevisions(3),
            clock,
            "scheduler-after-restart",
        )
        assert await restarted_worker.run_once()
        async with sessions.begin() as session:
            row = await session.get(ScheduledJobRow, job_id)
            assert row is not None and row.status == "skipped_stale"
            await session.execute(delete(ScheduledJobRow).where(ScheduledJobRow.id == job_id))


@pytest.mark.asyncio
async def test_expired_scheduler_lease_is_reclaimed() -> None:
    clock = FixedClock()
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            job_id = await PostgresJobQueue(session).enqueue(
                JobIntent(
                    HOUSE_ONE,
                    f"a09:{uuid4()}",
                    EventName.JOB_DUE.value,
                    clock.now(),
                    uuid4(),
                    1,
                )
            )
        async with sessions.begin() as session:
            assert (
                await PostgresJobQueue(session).claim("crashed", clock.now(), timedelta(seconds=30))
                is not None
            )
        clock.current += timedelta(seconds=31)
        async with sessions.begin() as session:
            queue = PostgresJobQueue(session)
            reclaimed = await queue.claim("restarted", clock.now(), timedelta(seconds=30))
            assert reclaimed is not None and reclaimed.id == job_id and reclaimed.attempts == 2
            with pytest.raises(JobLeaseLostError):
                await queue.settle(job_id, "crashed", clock.now(), "done")
            await queue.settle(job_id, "restarted", clock.now(), "done")
            await session.execute(delete(ScheduledJobRow).where(ScheduledJobRow.id == job_id))
