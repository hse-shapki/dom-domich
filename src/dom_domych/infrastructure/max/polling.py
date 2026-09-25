"""Dev polling: сначала durable inbox commit, только затем продвижение marker."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.max.updates import normalize_update
from dom_domych.infrastructure.postgres.inbox import save_inbox_event


class MaxPollingConsumer:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        client: MaxApiClient,
    ) -> None:
        self.sessions = sessions
        self.client = client
        self.marker: int | None = None

    async def poll_once(self) -> int:
        batch = await self.client.get_updates(marker=self.marker)
        received_at = datetime.now(UTC)
        async with self.sessions.begin() as session:
            for raw in batch.updates:
                source_key, event = normalize_update(raw, received_at)
                await save_inbox_event(session, source_key, event, raw, received_at)
        self.marker = batch.marker
        return len(batch.updates)
