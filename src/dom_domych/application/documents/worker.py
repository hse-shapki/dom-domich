"""Фоновый PDF: lease в PostgreSQL, рендер вне SQL и готовый файл в outbox."""

from datetime import timedelta
from typing import Protocol
from uuid import UUID, uuid4

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import (
    EntityEventPayload,
    EventEnvelope,
    EventName,
    EventSource,
)
from dom_domych.domain.documents.snapshot import DocumentMode, DocumentSnapshot
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.documents.renderer import RenderedDocument
from dom_domych.infrastructure.files.local import FileKind, LocalFileStore, StoredFile
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.documents import verify_snapshot_bytes
from dom_domych.infrastructure.postgres.inbox import save_domain_event
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow

logger = structlog.get_logger()


class DocumentRenderer(Protocol):
    async def render(self, snapshot: DocumentSnapshot) -> RenderedDocument: ...


class DocumentLeaseLost(RuntimeError):
    pass


class DocumentWorker:
    """Одна попытка за раз; после crash истёкший lease переходит другому worker."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        files: LocalFileStore,
        renderer: DocumentRenderer,
        clock: Clock,
        worker_id: str,
        *,
        lease_for: timedelta = timedelta(minutes=5),
        max_attempts: int = 5,
    ) -> None:
        if lease_for <= timedelta(0) or max_attempts < 1:
            raise ValueError("document worker needs positive lease and attempts")
        self.sessions = sessions
        self.files = files
        self.renderer = renderer
        self.clock = clock
        self.worker_id = worker_id
        self.lease_for = lease_for
        self.max_attempts = max_attempts

    async def run_once(self) -> bool:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(DocumentRow)
                .where(
                    or_(
                        DocumentRow.status == "queued",
                        (DocumentRow.status == "rendering")
                        & (DocumentRow.lease_until <= self.clock.now()),
                    )
                )
                .order_by(DocumentRow.created_at, DocumentRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return False
            row.status = "rendering"
            row.attempts += 1
            row.lease_owner = self.worker_id
            row.lease_until = self.clock.now() + self.lease_for
            document_id = row.id
        try:
            snapshot = verify_snapshot_bytes(row)
            rendered = await self.renderer.render(snapshot)
            if rendered.snapshot_sha256 != snapshot.sha256:
                raise ValueError("renderer used a different document snapshot")
            if rendered.template_revision != snapshot.template_revision:
                raise ValueError("renderer used a different template revision")
            stored = await self.files.put(
                snapshot.house_id, FileKind.DOCUMENT, rendered.mime_type, rendered.content
            )
            if stored.sha256 != rendered.sha256:
                raise ValueError("stored PDF hash does not match renderer")
            await self._finish(document_id, snapshot, stored)
        except Exception as exc:
            logger.error(
                "document_render_failed", document_id=str(document_id), error=type(exc).__name__
            )
            await self._fail(document_id, type(exc).__name__)
        return True

    async def _finish(
        self, document_id: UUID, snapshot: DocumentSnapshot, stored: StoredFile
    ) -> None:
        async with self.sessions.begin() as session:
            row = await self._locked_lease(session, document_id)
            if row.snapshot_sha256 != snapshot.sha256 or row.house_id != stored.house_id:
                raise ValueError("document changed during render")
            row.status = "ready"
            row.file_key = stored.file_key
            row.file_sha256 = stored.sha256
            row.file_mime_type = stored.mime_type
            row.file_size_bytes = stored.size_bytes
            row.file_retain_until = stored.retain_until
            row.ready_at = self.clock.now()
            row.lease_owner = None
            row.lease_until = None
            row.error_code = None
            await PostgresDeliveryQueue(session, self.clock).enqueue(
                DeliveryIntent(
                    house_id=row.house_id,
                    operation_key=f"document:file:{row.id}",
                    text=(
                        "Подготовлен документ Дом Домыч. "
                        + (
                            "Данные и действия в нём отмечены как демо."
                            if snapshot.mode is DocumentMode.DEMO
                            else "Это проект документа; официальная отправка не выполнена."
                        )
                    ),
                    recipient_id=row.recipient_id,
                    file_key=stored.file_key,
                )
            )
            await save_domain_event(
                session,
                EventEnvelope(
                    event_id=uuid4(),
                    source=EventSource.DOMAIN,
                    source_key=f"document:ready:{row.id}",
                    name=EventName.DOCUMENT_READY,
                    occurred_at=self.clock.now(),
                    received_at=self.clock.now(),
                    correlation_id=row.id,
                    house_id=row.house_id,
                    entity=EntityEventPayload(
                        entity_id=row.id,
                        entity_version=snapshot.case_revision,
                        case_id=row.case_id,
                        causation_id=row.id,
                    ),
                ),
            )

    async def _fail(self, document_id: UUID, error_code: str) -> None:
        async with self.sessions.begin() as session:
            try:
                row = await self._locked_lease(session, document_id)
            except DocumentLeaseLost:
                return
            row.status = "failed" if row.attempts >= self.max_attempts else "queued"
            row.lease_owner = None
            row.lease_until = None
            row.error_code = error_code[:100]

    async def _locked_lease(self, session: AsyncSession, document_id: UUID) -> DocumentRow:
        row = await session.scalar(
            select(DocumentRow).where(DocumentRow.id == document_id).with_for_update()
        )
        if (
            row is None
            or row.status != "rendering"
            or row.lease_owner != self.worker_id
            or row.lease_until is None
            or row.lease_until <= self.clock.now()
        ):
            raise DocumentLeaseLost("document lease expired or changed owner")
        return row
