"""A07: lease recovery и конкурентные workers на PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.application.jobs.inbox_worker import EventDispatcher, InboxWorker
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource, MessagePayload
from dom_domych.infrastructure.postgres.inbox import save_inbox_event
from dom_domych.infrastructure.postgres.inbox_worker import InboxStore, LeaseLostError
from dom_domych.infrastructure.postgres.models import InboxEventRow
from dom_domych.infrastructure.postgres.session import database_lifespan


class FixedClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


def event(clock: FixedClock) -> EventEnvelope:
    event_id = uuid4()
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"test:{event_id}",
        name=EventName.MESSAGE_RECEIVED,
        occurred_at=clock.now(),
        received_at=clock.now(),
        correlation_id=event_id,
        message=MessagePayload(
            chat_id="1", message_id=str(event_id), sender_user_id="2", text="Нет воды"
        ),
    )


def database_url_for_test() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in database_url:
        pytest.skip("A07 tests require a dedicated migrated dom_domych_test database")
    return database_url


@pytest.mark.asyncio
async def test_two_workers_claim_one_event_once() -> None:
    clock = FixedClock()
    received = event(clock)
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await session.execute(delete(InboxEventRow))
            await save_inbox_event(
                session, received.source_key, received, {"test": True}, clock.now()
            )
        seen: list[str] = []

        async def handle(item: EventEnvelope) -> None:
            seen.append(str(item.event_id))

        dispatcher = EventDispatcher({EventName.MESSAGE_RECEIVED: handle})
        results = await asyncio.gather(
            InboxWorker(sessions, dispatcher, clock, "w1").run_once(),
            InboxWorker(sessions, dispatcher, clock, "w2").run_once(),
        )
        assert results == [True, False] or results == [False, True]
        assert seen == [str(received.event_id)]
        async with sessions() as session:
            row = await session.get(InboxEventRow, received.event_id)
            assert row is not None and row.status == "done" and row.attempts == 1


@pytest.mark.asyncio
async def test_expired_lease_recovers_and_old_owner_cannot_finish() -> None:
    clock = FixedClock()
    received = event(clock)
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await session.execute(delete(InboxEventRow))
            await save_inbox_event(
                session, received.source_key, received, {"test": True}, clock.now()
            )
        async with sessions.begin() as session:
            first = await InboxStore(session).claim("crashed", clock.now(), timedelta(seconds=30))
            assert first is not None
        clock.current += timedelta(seconds=31)
        async with sessions.begin() as session:
            reclaimed = await InboxStore(session).claim(
                "restarted", clock.now(), timedelta(seconds=30)
            )
            assert reclaimed is not None and reclaimed.event_id == received.event_id
            with pytest.raises(LeaseLostError):
                await InboxStore(session).finish(received.event_id, "crashed", clock.now())
            await InboxStore(session).heartbeat(
                received.event_id, "restarted", clock.now(), timedelta(seconds=30)
            )
            await InboxStore(session).finish(received.event_id, "restarted", clock.now())
        async with sessions() as session:
            row = await session.scalar(
                select(InboxEventRow).where(InboxEventRow.id == received.event_id)
            )
            assert row is not None and row.status == "done" and row.attempts == 2


@pytest.mark.asyncio
async def test_failed_handler_retries_then_dead_letters() -> None:
    clock = FixedClock()
    received = event(clock)
    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await session.execute(delete(InboxEventRow))
            await save_inbox_event(session, received.source_key, received, {}, clock.now())

        async def fail_handler(_item: EventEnvelope) -> None:
            raise RuntimeError("synthetic failure")

        worker = InboxWorker(
            sessions,
            EventDispatcher({EventName.MESSAGE_RECEIVED: fail_handler}),
            clock,
            "w1",
            max_attempts=2,
        )
        assert await worker.run_once()
        assert not await worker.run_once()
        clock.current += timedelta(seconds=5)
        assert await worker.run_once()
        async with sessions() as session:
            row = await session.get(InboxEventRow, received.event_id)
            assert row is not None and row.status == "dead" and row.attempts == 2
