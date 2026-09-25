"""Периодическая идемпотентная очистка FileStore и payload очередей."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.retention import RedactionResult, redact_expired_payloads


class RetentionMaintenance:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        files: LocalFileStore,
        clock: Clock,
        retention: timedelta,
    ) -> None:
        if retention <= timedelta(0):
            raise ValueError("retention must be positive")
        self.sessions = sessions
        self.files = files
        self.clock = clock
        self.retention = retention

    async def run_once(self) -> tuple[RedactionResult, int]:
        now = self.clock.now()
        async with self.sessions() as session:
            house_ids = tuple(await session.scalars(select(HouseRow.id)))
        deleted_files = 0
        for house_id in house_ids:
            deleted_files += await self.files.purge_expired(house_id, now)
        async with self.sessions.begin() as session:
            redacted = await redact_expired_payloads(session, now - self.retention)
        return redacted, deleted_files
