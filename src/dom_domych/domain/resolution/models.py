"""Проверка фактического результата исходной аудиторией дела."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from dom_domych.domain.polls.models import PollKind, PollState, PollStatus
from dom_domych.domain.polls.policy import ResolutionOutcome


class ResolutionStatus(StrEnum):
    CHECKING = "checking"
    CLOSED = "closed"
    REOPENED = "reopened"
    UNCONFIRMED = "resolution_unconfirmed"


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
    poll_version_at_decision: int | None = None
    decided_at: datetime | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.case_version_at_start <= 0 or self.version <= 0:
            raise ValueError("resolution needs positive version")
        for value in (self.started_at, self.decided_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
                raise ValueError("resolution times must use UTC")
        if self.status is ResolutionStatus.CHECKING and self.decided_at is not None:
            raise ValueError("checking resolution cannot have decision time")
        if self.status is not ResolutionStatus.CHECKING and (
            self.decided_at is None or self.poll_version_at_decision is None
        ):
            raise ValueError("decided resolution needs poll version and time")

    def decide(self, poll: PollState, at: datetime) -> "ResolutionState":
        if self.status is not ResolutionStatus.CHECKING:
            return self
        definition = poll.definition
        if (
            definition.kind is not PollKind.RESOLUTION_CHECK
            or definition.poll_id != self.poll_id
            or definition.case_id != self.case_id
            or definition.house_id != self.house_id
            or definition.audience_id != self.original_audience_id
            or poll.status is not PollStatus.CLOSED
            or not isinstance(poll.outcome, ResolutionOutcome)
        ):
            raise ResolutionConflict("poll does not match finalized resolution check")
        status = {
            ResolutionOutcome.CLOSED: ResolutionStatus.CLOSED,
            ResolutionOutcome.REOPENED: ResolutionStatus.REOPENED,
            ResolutionOutcome.UNCONFIRMED: ResolutionStatus.UNCONFIRMED,
        }.get(poll.outcome)
        if status is None:
            raise ResolutionConflict("poll has no final resolution outcome")
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("decision time must use UTC")
        if at < self.started_at:
            raise ResolutionConflict("decision precedes resolution check")
        return replace(
            self,
            status=status,
            poll_version_at_decision=poll.version,
            decided_at=at,
            version=self.version + 1,
        )
