"""PostgreSQL-снимки документов и house-scoped DocumentPort."""

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.domain.documents.snapshot import DocumentMode, DocumentSnapshot
from dom_domych.domain.ports.core import DocumentRef
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.models import HouseRow, ResidencyRow
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow


class PostgresDocuments:
    """Подготовка фиксирует bytes и hash; рендер выполняет отдельный worker."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def prepare(
        self,
        snapshot: DocumentSnapshot,
        recipient_id: UUID,
        *,
        operation_key: str,
    ) -> DocumentRef:
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid document operation key")
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(DocumentRow).where(
                    DocumentRow.house_id == snapshot.house_id,
                    DocumentRow.operation_key == operation_key,
                )
            )
            if existing is not None:
                return self._matching_ref(existing, snapshot, recipient_id)
            await self._validate_sources(session, snapshot, recipient_id)
            document_id = uuid4()
            inserted = await session.scalar(
                insert(DocumentRow)
                .values(
                    id=document_id,
                    house_id=snapshot.house_id,
                    case_id=snapshot.case_id,
                    audience_id=snapshot.audience_id,
                    poll_id=snapshot.poll_id,
                    request_id=snapshot.request_id,
                    recipient_id=recipient_id,
                    operation_key=operation_key,
                    kind=snapshot.kind.value,
                    mode=snapshot.mode.value,
                    template_revision=snapshot.template_revision,
                    snapshot_bytes=snapshot.canonical_bytes(),
                    snapshot_sha256=snapshot.sha256,
                    status="queued",
                    created_at=snapshot.created_at,
                    attempts=0,
                )
                .on_conflict_do_nothing(index_elements=["house_id", "operation_key"])
                .returning(DocumentRow.id)
            )
            if inserted is not None:
                return DocumentRef(
                    document_id,
                    snapshot.house_id,
                    snapshot.case_id,
                    "queued",
                    None,
                    snapshot.sha256,
                )
            existing = await session.scalar(
                select(DocumentRow).where(
                    DocumentRow.house_id == snapshot.house_id,
                    DocumentRow.operation_key == operation_key,
                )
            )
            if existing is None:
                raise RuntimeError("conflicting document disappeared")
            return self._matching_ref(existing, snapshot, recipient_id)

    @classmethod
    def _matching_ref(
        cls, existing: DocumentRow, snapshot: DocumentSnapshot, recipient_id: UUID
    ) -> DocumentRef:
        if (
            existing.snapshot_sha256 != snapshot.sha256
            or existing.recipient_id != recipient_id
            or existing.kind != snapshot.kind.value
        ):
            raise ValueError("document operation key conflicts with other contents")
        return cls._ref(existing)

    async def get(self, document_id: UUID, house_id: UUID) -> DocumentRef | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(DocumentRow).where(
                    DocumentRow.id == document_id, DocumentRow.house_id == house_id
                )
            )
            return self._ref(row) if row is not None else None

    @staticmethod
    def _ref(row: DocumentRow) -> DocumentRef:
        return DocumentRef(
            document_id=row.id,
            house_id=row.house_id,
            case_id=row.case_id,
            status=row.status,
            file_key=row.file_key,
            snapshot_hash=row.snapshot_sha256,
        )

    @staticmethod
    async def _validate_sources(
        session: AsyncSession, snapshot: DocumentSnapshot, recipient_id: UUID
    ) -> None:
        house = await session.get(HouseRow, snapshot.house_id)
        case = await session.scalar(
            select(CaseRow).where(
                CaseRow.id == snapshot.case_id, CaseRow.house_id == snapshot.house_id
            )
        )
        audience = await session.scalar(
            select(AudienceSnapshotRow).where(
                AudienceSnapshotRow.id == snapshot.audience_id,
                AudienceSnapshotRow.house_id == snapshot.house_id,
            )
        )
        if (
            house is None
            or house.address != snapshot.house_address
            or (snapshot.mode == DocumentMode.DEMO) != house.demo
            or case is None
            or case.version != snapshot.case_revision
            or audience is None
            or audience.criteria_revision != snapshot.audience_revision
        ):
            raise ValueError("document snapshot does not match current case or audience")
        if snapshot.poll_id is not None:
            poll = await PostgresPollRepository(session).get_state(
                snapshot.poll_id, snapshot.house_id
            )
            if (
                poll is None
                or poll.definition.case_id != snapshot.case_id
                or poll.definition.audience_id != snapshot.audience_id
                or poll.version != snapshot.poll_revision
                or poll.definition.policy.revision != snapshot.policy_revision
                or poll.tally != snapshot.tally
            ):
                raise ValueError("document snapshot does not match current poll")
        if snapshot.request_id is not None:
            request = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == snapshot.request_id,
                    RequestRow.house_id == snapshot.house_id,
                )
            )
            if (
                request is None
                or request.case_id != snapshot.case_id
                or request.draft_version != snapshot.request_revision
            ):
                raise ValueError("document snapshot does not match current request")
        if not await PostgresDocuments._active_resident(
            session, snapshot.house_id, recipient_id, snapshot.created_at
        ):
            raise ValueError("document recipient is not a verified resident of the house")

    @staticmethod
    async def _active_resident(
        session: AsyncSession, house_id: UUID, resident_id: UUID, at: datetime
    ) -> bool:
        residency = await session.scalar(
            select(ResidencyRow.id)
            .where(
                ResidencyRow.house_id == house_id,
                ResidencyRow.resident_id == resident_id,
                ResidencyRow.confirmed.is_(True),
                ResidencyRow.adult.is_(True),
                ResidencyRow.valid_from <= at,
                or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > at),
            )
            .limit(1)
        )
        return residency is not None


def verify_snapshot_bytes(row: DocumentRow) -> DocumentSnapshot:
    """Перед рендером сверяет сохранённые bytes с hash и ключами БД."""

    if hashlib.sha256(row.snapshot_bytes).hexdigest() != row.snapshot_sha256:
        raise ValueError("document snapshot hash mismatch")
    snapshot = DocumentSnapshot.from_canonical_bytes(row.snapshot_bytes)
    if (
        snapshot.house_id != row.house_id
        or snapshot.case_id != row.case_id
        or snapshot.audience_id != row.audience_id
        or snapshot.poll_id != row.poll_id
        or snapshot.request_id != row.request_id
        or snapshot.kind.value != row.kind
        or snapshot.mode.value != row.mode
        or snapshot.template_revision != row.template_revision
    ):
        raise ValueError("document snapshot metadata mismatch")
    return snapshot
