"""Формулировка инициативы версионируется отдельно от общего дела Катерины."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


class InitiativeError(Exception):
    """Недопустимая ревизия или право доступа к инициативе."""


class InitiativeForbidden(InitiativeError):
    """Команда пришла не от автора или из чужого дома."""


class InitiativeConflict(InitiativeError):
    """Изменился case/initiative или ключ операции уже занят другим содержимым."""


@dataclass(frozen=True, slots=True)
class InitiativeRevision:
    revision: int
    wording: str
    audience_id: UUID
    poll_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if self.revision <= 0 or not self.wording.strip():
            raise ValueError("initiative revision needs number and wording")
        if len(self.wording) > 4_000:
            raise ValueError("initiative wording exceeds safe limit")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must use UTC")


@dataclass(frozen=True, slots=True)
class InitiativeState:
    case_id: UUID
    house_id: UUID
    author_id: UUID
    case_version: int
    revisions: tuple[InitiativeRevision, ...]

    def __post_init__(self) -> None:
        if self.case_version <= 0 or not self.revisions:
            raise ValueError("initiative needs case version and first revision")
        if tuple(item.revision for item in self.revisions) != tuple(
            range(1, len(self.revisions) + 1)
        ):
            raise ValueError("initiative revisions must be consecutive")

    @property
    def current(self) -> InitiativeRevision:
        return self.revisions[-1]

    def revise(self, revision: InitiativeRevision, expected_revision: int) -> "InitiativeState":
        if self.current.revision != expected_revision:
            raise InitiativeConflict("initiative revision changed")
        if revision.revision != expected_revision + 1:
            raise InitiativeConflict("new revision must follow current revision")
        return InitiativeState(
            case_id=self.case_id,
            house_id=self.house_id,
            author_id=self.author_id,
            case_version=self.case_version,
            revisions=self.revisions + (revision,),
        )
