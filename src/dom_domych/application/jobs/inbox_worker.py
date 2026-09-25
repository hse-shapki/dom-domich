"""A07 worker вызывает зарегистрированный handler вне SQL-транзакции."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EventEnvelope, EventName
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.inbox_worker import InboxStore, LeaseLostError

EventHandler = Callable[[EventEnvelope], Awaitable[bool | None]]
logger = structlog.get_logger()


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class EventDispatcher:
    """Позволяет A/K/Z последовательно предложить несколько handlers одному событию."""

    def __init__(self, handlers: dict[EventName, EventHandler | list[EventHandler]]) -> None:
        self.handlers: dict[EventName, list[EventHandler]] = {}
        for event_name, configured in handlers.items():
            self.handlers[event_name] = configured if isinstance(configured, list) else [configured]

    def register(self, event_name: EventName, handler: EventHandler) -> None:
        self.handlers.setdefault(event_name, []).append(handler)

    async def handle(self, event: EventEnvelope) -> None:
        for handler in self.handlers.get(event.name, ()):
            handled = await handler(event)
            if handled is not False:
                return
        raise LookupError(f"no handler accepted {event.name}")


class InboxWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        dispatcher: EventDispatcher,
        clock: Clock,
        worker_id: str,
        lease_for: timedelta = timedelta(seconds=30),
        max_attempts: int = 5,
    ) -> None:
        if lease_for <= timedelta(0) or max_attempts < 1:
            raise ValueError("worker lease and max_attempts must be positive")
        self.sessions = sessions
        self.dispatcher = dispatcher
        self.clock = clock
        self.worker_id = worker_id
        self.lease_for = lease_for
        self.max_attempts = max_attempts

    async def run_once(self) -> bool:
        async with self.sessions.begin() as session:
            event = await InboxStore(session).claim(
                self.worker_id, self.clock.now(), self.lease_for
            )
        if event is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(event.event_id))
        try:
            await self.dispatcher.handle(event)
            async with self.sessions.begin() as session:
                await InboxStore(session).finish(event.event_id, self.worker_id, self.clock.now())
            logger.info("inbox_event_done", event_id=str(event.event_id), name=event.name)
        except Exception as exc:
            logger.error(
                "inbox_event_failed", event_id=str(event.event_id), error=type(exc).__name__
            )
            async with self.sessions.begin() as session:
                await InboxStore(session).fail(
                    event.event_id,
                    self.worker_id,
                    self.clock.now(),
                    retry_after=timedelta(seconds=5),
                    max_attempts=self.max_attempts,
                )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        return True

    async def _heartbeat(self, event_id: UUID) -> None:
        interval = self.lease_for.total_seconds() / 3
        while True:
            await asyncio.sleep(interval)
            async with self.sessions.begin() as session:
                try:
                    await InboxStore(session).heartbeat(
                        event_id, self.worker_id, self.clock.now(), self.lease_for
                    )
                except LeaseLostError as exc:
                    logger.warning(
                        "inbox_heartbeat_stopped",
                        event_id=str(event_id),
                        error=type(exc).__name__,
                    )
                    return
