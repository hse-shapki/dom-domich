"""PostgreSQL-репозиторий снимков аудитории."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.domain.audiences.models import (
    AudienceMember,
    AudienceScope,
    AudienceSnapshot,
    ScopeKind,
)
from dom_domych.infrastructure.postgres.z_audience_models import (
    AudienceMemberRow,
    AudienceSnapshotRow,
)


class PostgresAudienceRepository:
    """Работает в переданной UoW; её владелец делает один общий commit."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, audience_id: UUID) -> AudienceSnapshot | None:
        row = await self.session.get(AudienceSnapshotRow, audience_id)
        if row is None:
            return None
        members = (
            await self.session.scalars(
                select(AudienceMemberRow)
                .where(AudienceMemberRow.audience_id == audience_id)
                .order_by(AudienceMemberRow.resident_id)
            )
        ).all()
        return AudienceSnapshot(
            audience_id=row.id,
            house_id=row.house_id,
            scope=AudienceScope(
                kind=ScopeKind(row.scope_kind),
                entrance=row.entrance,
                floor=row.floor,
                riser_id=row.riser_id,
                riser_kind=row.riser_kind,
            ),
            criteria_revision=row.criteria_revision,
            members=tuple(
                AudienceMember(member.resident_id, member.reachable_at_snapshot)
                for member in members
            ),
            created_at=row.created_at,
            supersedes_id=row.supersedes_id,
        )

    async def get_scoped(self, audience_id: UUID, house_id: UUID) -> AudienceSnapshot | None:
        row = await self.session.scalar(
            select(AudienceSnapshotRow.id).where(
                AudienceSnapshotRow.id == audience_id, AudienceSnapshotRow.house_id == house_id
            )
        )
        return await self.get(row) if row is not None else None

    async def save_once(self, snapshot: AudienceSnapshot, operation_key: str) -> AudienceSnapshot:
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid audience operation key")
        statement = (
            insert(AudienceSnapshotRow)
            .values(
                id=snapshot.audience_id,
                house_id=snapshot.house_id,
                operation_key=operation_key,
                scope_kind=snapshot.scope.kind.value,
                entrance=snapshot.scope.entrance,
                floor=snapshot.scope.floor,
                riser_id=snapshot.scope.riser_id,
                riser_kind=snapshot.scope.riser_kind,
                criteria_revision=snapshot.criteria_revision,
                created_at=snapshot.created_at,
                supersedes_id=snapshot.supersedes_id,
            )
            .on_conflict_do_nothing()
            .returning(AudienceSnapshotRow.id)
        )
        inserted_id = await self.session.scalar(statement)
        if inserted_id is not None:
            if snapshot.members:
                await self.session.execute(
                    insert(AudienceMemberRow),
                    [
                        {
                            "audience_id": snapshot.audience_id,
                            "house_id": snapshot.house_id,
                            "resident_id": member.resident_id,
                            "reachable_at_snapshot": member.reachable_at_snapshot,
                        }
                        for member in snapshot.members
                    ],
                )
            return snapshot
        existing_id = await self.session.scalar(
            select(AudienceSnapshotRow.id).where(
                AudienceSnapshotRow.house_id == snapshot.house_id,
                AudienceSnapshotRow.operation_key == operation_key,
            )
        )
        if existing_id is None:
            raise ValueError("audience revision already superseded")
        existing = await self.get(existing_id)
        if existing is None:
            raise RuntimeError("audience disappeared during idempotent read")
        if existing.scope != snapshot.scope or existing.supersedes_id != snapshot.supersedes_id:
            raise ValueError("operation key conflicts with a different audience")
        return existing
