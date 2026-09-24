"""Проверка фактического результата исходной аудиторией дела."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class ResolutionStatus(StrEnum):
    CHECKING = "checking"


class ResolutionError(Exception):
    """Нельзя начать или завершить проверку при текущем состоянии."""


class ResolutionForbidden(ResolutionError):
    """Событие или данные относятся к чужому дому/делу."""


class ResolutionConflict(ResolutionError):
    """Изменились дело, poll или операция проверки."""


@dataclass(frozen=True, slots=True)
class ResolutionState:
    check_id: UUID
    case_id: UUID
    house_id: UUID
    request_id: UUID
    original_audience_id: UUID
    poll_id: UUID
    case_version_at_start: int
    done_event_id: UUID
    started_at: datetime
    status: ResolutionStatus = ResolutionStatus.CHECKING
    version: int = 1

    def __post_init__(self) -> None:
        if self.case_version_at_start <= 0 or self.version <= 0:
            raise ValueError("resolution needs positive version")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() != timedelta(
            0
        ):
            raise ValueError("started_at must use UTC")
