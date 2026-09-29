"""Готовность вспомогательного PDF не заменяет основное обращение K."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.documents.snapshot import DocumentKind
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow


class DocumentReadyEventHandler:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.name is not EventName.DOCUMENT_READY:
            return False
        if event.source is not EventSource.DOMAIN or event.house_id is None or event.entity is None:
            raise ValueError("UNTRUSTED_DOCUMENT_EVENT")
        async with self.sessions() as session:
            row = await session.scalar(
                select(DocumentRow).where(
                    DocumentRow.id == event.entity.entity_id,
                    DocumentRow.house_id == event.house_id,
                    DocumentRow.case_id == event.entity.case_id,
                    DocumentRow.status == "ready",
                )
            )
            if row is None:
                raise ValueError("DOCUMENT_NOT_READY")
            # Appeal проходит дальше к K request binding; прочие уже доставляются лично.
            return row.kind != DocumentKind.APPEAL.value
