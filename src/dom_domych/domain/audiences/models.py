"""Доменная область адресной аудитории; MAX и SQLAlchemy здесь не используются."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ScopeKind(StrEnum):
    HOUSE = "house"
    ENTRANCE = "entrance"
    FLOOR = "floor"
    RISER = "riser"


class ResidencyView(Protocol):
    """Минимальные данные реестра A для выбора аудитории без зависимости от ORM."""

    @property
    def resident_id(self) -> UUID: ...

    @property
    def house_id(self) -> UUID: ...

    @property
    def entrance(self) -> int: ...

    @property
    def floor(self) -> int: ...

    @property
    def risers(self) -> frozenset["RiserRef"]: ...

    @property
    def confirmed(self) -> bool: ...

    @property
    def adult(self) -> bool: ...

    @property
    def active(self) -> bool: ...

    @property
    def dm_reachable(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RiserRef:
    riser_id: UUID
    kind: str

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("riser kind is required")


@dataclass(frozen=True, slots=True)
class AudienceScope:
    kind: ScopeKind
    entrance: int | None = None
    floor: int | None = None
    riser_id: UUID | None = None
    riser_kind: str | None = None

    def __post_init__(self) -> None:
        if self.entrance is not None and self.entrance <= 0:
            raise ValueError("entrance must be positive")
        if self.kind == ScopeKind.HOUSE:
            valid = all(
                value is None
                for value in (self.entrance, self.floor, self.riser_id, self.riser_kind)
            )
        elif self.kind == ScopeKind.ENTRANCE:
            valid = self.entrance is not None and all(
                value is None for value in (self.floor, self.riser_id, self.riser_kind)
            )
        elif self.kind == ScopeKind.FLOOR:
            valid = (
                self.entrance is not None
                and self.floor is not None
                and all(value is None for value in (self.riser_id, self.riser_kind))
            )
        elif self.kind == ScopeKind.RISER:
            valid = (
                self.riser_id is not None
                and bool(self.riser_kind)
                and all(value is None for value in (self.entrance, self.floor))
            )
        else:
            valid = False
        if not valid:
            raise ValueError(f"invalid scope fields for {self.kind}")

    def matches(self, residency: "ResidencyView") -> bool:
        if self.kind == ScopeKind.HOUSE:
            return True
        if self.kind == ScopeKind.ENTRANCE:
            return residency.entrance == self.entrance
        if self.kind == ScopeKind.FLOOR:
            return residency.entrance == self.entrance and residency.floor == self.floor
        if self.riser_id is None or self.riser_kind is None:
            raise ValueError("riser scope is missing an explicit riser")
        return RiserRef(self.riser_id, self.riser_kind) in residency.risers


@dataclass(frozen=True, slots=True)
class AudienceMember:
    resident_id: UUID
    reachable_at_snapshot: bool


@dataclass(frozen=True, slots=True)
class AudienceSnapshot:
    audience_id: UUID
    house_id: UUID
    scope: AudienceScope
    criteria_revision: int
    members: tuple[AudienceMember, ...]
    created_at: datetime
    supersedes_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.criteria_revision <= 0:
            raise ValueError("criteria_revision must be positive")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(
            0
        ):
            raise ValueError("created_at must use UTC")
        ids = [member.resident_id for member in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("audience members must be unique")

    @property
    def eligible_count(self) -> int:
        return len(self.members)

    @property
    def reachable_count(self) -> int:
        return sum(member.reachable_at_snapshot for member in self.members)
