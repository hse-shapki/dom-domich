"""Запуск due jobs через общий dispatcher с проверкой версии сущности."""

import asyncio
from datetime import timedelta
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.jobs import (
    DueJob,
    JobLeaseLostError,
    PostgresJobQueue,
)

logger = structlog.get_logger()


class CurrentRevisionPort(Protocol):
    """K/Z adapter читает версию под house scope; consumer повторно проверяет её под lock."""

    async def current_version(self, job: DueJob) -> int | None: ...


class RevisionRouter:
    """A14 composition seam: K/Z регистрируют reader для принадлежащих им событий."""

    def __init__(self) -> None:
        self._readers: dict[EventName, CurrentRevisionPort] = {}

    def register(self, event_name: EventName, reader: CurrentRevisionPort) -> None:
        if event_name in self._readers:
            raise ValueError(f"revision reader already registered for {event_name}")
        self._readers[event_name] = reader

    async def current_version(self, job: DueJob) -> int | None:
        reader = self._readers.get(job.event_name)
        if reader is None:
            raise LookupError(f"no revision reader registered for {job.event_name}")
        return await reader.current_version(job)


class JobScheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        dispatcher: EventDispatcher,
        revisions: CurrentRevisionPort,
        clock: Clock,
        worker_id: str,
        max_attempts: int = 5,
        lease_for: timedelta = timedelta(seconds=60),
    ) -> None:
        if max_attempts < 1 or lease_for <= timedelta(0):
            raise ValueError("max_attempts must be positive")
        self.sessions = sessions
        self.dispatcher = dispatcher
        self.revisions = revisions
        self.clock = clock
        self.worker_id = worker_id
        self.max_attempts = max_attempts
        self.lease_for = lease_for

    async def run_once(self) -> bool:
        async with self.sessions.begin() as session:
            job = await PostgresJobQueue(session).claim(
                self.worker_id, self.clock.now(), self.lease_for
            )
        if job is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            current = await self.revisions.current_version(job)
            if current != job.expected_version:
                await self._settle(job.id, "skipped_stale")
                return True
            await self.dispatcher.handle(
                EventEnvelope(
                    event_id=job.id,
                    source=EventSource.SCHEDULER,
                    source_key=f"job:{job.id}",
                    name=job.event_name,
                    occurred_at=job.due_at,
                    received_at=self.clock.now(),
                    correlation_id=job.id,
                    house_id=job.house_id,
                    entity=EntityEventPayload(
                        entity_id=job.entity_id, entity_version=job.expected_version
                    ),
                )
            )
            await self._settle(job.id, "done")
        except Exception as exc:
            logger.error("job_failed", job_id=str(job.id), error=type(exc).__name__)
            if job.attempts >= self.max_attempts:
                await self._settle(job.id, "dead", error_code=type(exc).__name__)
            else:
                delay = timedelta(seconds=min(60, 5 * (2 ** (job.attempts - 1))))
                await self._settle(
                    job.id, "pending", error_code=type(exc).__name__, retry_after=delay
                )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        return True

    async def _heartbeat(self, job_id: UUID) -> None:
        interval = self.lease_for.total_seconds() / 3
        while True:
            await asyncio.sleep(interval)
            async with self.sessions.begin() as session:
                try:
                    await PostgresJobQueue(session).heartbeat(
                        job_id,
                        self.worker_id,
                        self.clock.now(),
                        self.lease_for,
                    )
                except JobLeaseLostError:
                    return

    async def _settle(
        self,
        job_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
        retry_after: timedelta | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            await PostgresJobQueue(session).settle(
                job_id,
                self.worker_id,
                self.clock.now(),
                status,
                error_code=error_code,
                retry_after=retry_after,
            )
        logger.info("job_settled", job_id=str(job_id), status=status, error_code=error_code)
