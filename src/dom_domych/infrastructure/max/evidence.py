"""Загрузка фотографий из сохранённого MAX Update в house-scoped FileStore."""

import json
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.infrastructure.files.local import FileKind, LocalFileStore, StoredFile
from dom_domych.infrastructure.max.media import MaxMediaTransport, extract_image_urls
from dom_domych.infrastructure.postgres.models import (
    HouseRow,
    InboxEventRow,
    ResidencyRow,
    ResidentRow,
)


class EvidenceSourceDenied(ValueError):
    pass


class MaxEvidenceLoader:
    """K вызывает с доверенным house_id и event_id, после проверки прав автора."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        media: MaxMediaTransport,
        files: LocalFileStore,
    ) -> None:
        self.sessions = sessions
        self.media = media
        self.files = files

    async def load_images(self, event_id: UUID, house_id: UUID) -> tuple[StoredFile, ...]:
        async with self.sessions() as session:
            row = await session.get(InboxEventRow, event_id)
            if row is None or row.normalized_event is None:
                raise EvidenceSourceDenied("MAX event not found")
            event = EventEnvelope.model_validate_json(json.dumps(row.normalized_event))
            if (
                event.source is not EventSource.MAX
                or event.name not in {EventName.MESSAGE_RECEIVED, EventName.ATTACHMENT_RECEIVED}
                or event.message is None
            ):
                raise EvidenceSourceDenied("event is not an incoming MAX message")
            await self._check_author(session, event, house_id)
            urls = extract_image_urls(row.raw_update)
        stored: list[StoredFile] = []
        for url in urls:
            mime, content = await self.media.download_image(url)
            stored.append(await self.files.put(house_id, FileKind.EVIDENCE, mime, content))
        return tuple(stored)

    @staticmethod
    async def _check_author(session: AsyncSession, event: EventEnvelope, house_id: UUID) -> None:
        assert event.message is not None
        message = event.message
        if message.chat_id.startswith("dm:"):
            selected = await session.scalar(
                select(ResidentRow.active_house_id).where(
                    ResidentRow.max_user_id == message.sender_user_id
                )
            )
            if selected != house_id:
                raise EvidenceSourceDenied("private message has no selected house")
        else:
            mapped = await session.scalar(
                select(HouseRow.id).where(HouseRow.max_chat_id == message.chat_id)
            )
            if mapped != house_id:
                raise EvidenceSourceDenied("message chat belongs to another house")
        actor = await session.scalar(
            select(ResidentRow.id)
            .join(ResidencyRow, ResidencyRow.resident_id == ResidentRow.id)
            .where(
                ResidentRow.max_user_id == message.sender_user_id,
                ResidencyRow.house_id == house_id,
                ResidencyRow.confirmed.is_(True),
                ResidencyRow.adult.is_(True),
                ResidencyRow.valid_from <= event.received_at,
                or_(
                    ResidencyRow.valid_until.is_(None),
                    ResidencyRow.valid_until > event.received_at,
                ),
            )
            .limit(1)
        )
        if actor is None:
            raise EvidenceSourceDenied("MAX author not confirmed in house")
