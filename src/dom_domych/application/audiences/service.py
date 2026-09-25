"""Выбор подходящих жителей и сохранение неизменяемого снимка аудитории."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.domain.audiences.models import (
    AudienceMember,
    AudienceScope,
    AudienceSnapshot,
    ResidencyView,
)


class TrustedHouseContext(Protocol):
    @property
    def house_id(self) -> UUID: ...


class ResidentDirectory(Protocol):
    async def list_house_residencies(self, house_id: UUID) -> Sequence[ResidencyView]: ...


class AudienceRepository(Protocol):
    async def get(self, audience_id: UUID) -> AudienceSnapshot | None: ...

    async def save_once(self, snapshot: AudienceSnapshot, operation_key: str) -> AudienceSnapshot:
        """Сохраняет key и единственного successor атомарно; иной payload даёт конфликт."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class AudienceService:
    """Возвращает snapshot; реальная реализация repository работает в короткой UoW."""

    def __init__(
        self,
        directory: ResidentDirectory,
        repository: AudienceRepository,
        clock: Clock,
    ) -> None:
        self.directory = directory
        self.repository = repository
        self.clock = clock

    async def resolve(
        self,
        scope: AudienceScope,
        context: TrustedHouseContext,
        *,
        operation_key: str,
        supersedes_id: UUID | None = None,
    ) -> AudienceSnapshot:
        """Дедуплицирует жителей и отделяет право голоса от доступности лички."""

        if not operation_key:
            raise ValueError("operation_key is required")
        revision = 1
        if supersedes_id is not None:
            previous = await self.repository.get(supersedes_id)
            if previous is None or previous.house_id != context.house_id:
                raise ValueError("superseded audience is missing or belongs to another house")
            revision = previous.criteria_revision + 1

        residencies = await self.directory.list_house_residencies(context.house_id)
        reachable_by_resident: dict[UUID, bool] = {}
        for residency in residencies:
            if residency.house_id != context.house_id:
                continue
            if not residency.active or not residency.confirmed or not residency.adult:
                continue
            if not scope.matches(residency):
                continue
            reachable_by_resident[residency.resident_id] = (
                reachable_by_resident.get(residency.resident_id, False) or residency.dm_reachable
            )

        members = tuple(
            AudienceMember(resident_id=resident_id, reachable_at_snapshot=reachable)
            for resident_id, reachable in sorted(
                reachable_by_resident.items(), key=lambda item: item[0].bytes
            )
        )
        snapshot = AudienceSnapshot(
            audience_id=uuid4(),
            house_id=context.house_id,
            scope=scope,
            criteria_revision=revision,
            members=members,
            created_at=self.clock.now(),
            supersedes_id=supersedes_id,
        )
        return await self.repository.save_once(snapshot, operation_key)
