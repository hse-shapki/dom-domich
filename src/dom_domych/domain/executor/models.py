"""Доменная модель моделируемого исполнителя, отдельно от workflow дела."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class ExternalStatus(StrEnum):
    SUBMITTED = "submitted"
    REGISTERED = "registered"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class ExecutorError(Exception):
    """Нарушен переход или право доступа к demo executor."""


class ExecutorForbidden(ExecutorError):
    """У actor нет нужной служебной capability."""


class ExecutorConflict(ExecutorError):
    """Команда несовместима с текущим состоянием или idempotency key."""


class ExecutorNotFound(ExecutorError):
    """Операция не найдена в пространстве данного дома."""


@dataclass(frozen=True, slots=True)
class ApprovedDraft:
    """Ссылка на утверждённую редакцию черновика из доверенного RequestService."""

    house_id: UUID
    request_id: UUID
    draft_id: UUID
    draft_revision: int
    content_sha256: str

    def __post_init__(self) -> None:
        if (
            self.draft_revision <= 0
            or len(self.content_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.content_sha256
            )
        ):
            raise ValueError("approved draft needs revision and SHA-256")


@dataclass(frozen=True, slots=True)
class DemoOperation:
    operation_id: UUID
    operation_key: str
    draft: ApprovedDraft
    status: ExternalStatus
    submitted_at: datetime
    registration_number: str | None = None
    registered_at: datetime | None = None
    status_updated_at: datetime | None = None
    processed_event_ids: frozenset[UUID] = frozenset()
    source: str = "demo_executor"

    def __post_init__(self) -> None:
        if self.source != "demo_executor":
            raise ValueError("demo operation source must be demo_executor")
        for name, value in (
            ("submitted_at", self.submitted_at),
            ("registered_at", self.registered_at),
            ("status_updated_at", self.status_updated_at),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() != timedelta(0)
            ):
                raise ValueError(f"{name} must use UTC")
        if self.status is not ExternalStatus.SUBMITTED and (
            self.registration_number is None or self.registered_at is None
        ):
            raise ValueError("registered status needs number and time")
        if self.status is ExternalStatus.SUBMITTED and (
            self.registration_number is not None or self.registered_at is not None
        ):
            raise ValueError("submitted status cannot have a registration")

    def register(self, at: datetime) -> tuple["DemoOperation", bool]:
        if self.status is not ExternalStatus.SUBMITTED:
            return self, False
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("registration time must use UTC")
        if at < self.submitted_at:
            raise ExecutorConflict("registration precedes submission")
        return (
            replace(
                self,
                status=ExternalStatus.REGISTERED,
                registration_number=f"DEMO-{self.operation_id.hex[:12].upper()}",
                registered_at=at,
                status_updated_at=at,
            ),
            True,
        )

    def change_status(
        self, status: ExternalStatus, at: datetime, source_event_id: UUID
    ) -> tuple["DemoOperation", bool]:
        if source_event_id in self.processed_event_ids:
            return self, False
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("status time must use UTC")
        if self.status_updated_at is not None and at < self.status_updated_at:
            raise ExecutorConflict("status update precedes current state")
        if self.status not in {ExternalStatus.REGISTERED, ExternalStatus.IN_PROGRESS}:
            raise ExecutorConflict("operation is not open for status update")
        if status not in {ExternalStatus.IN_PROGRESS, ExternalStatus.DONE}:
            raise ExecutorConflict("status transition is not allowed")
        if (
            self.status is ExternalStatus.IN_PROGRESS
            and status is ExternalStatus.IN_PROGRESS
        ):
            return self, False
        return (
            replace(
                self,
                status=status,
                status_updated_at=at,
                processed_event_ids=self.processed_event_ids | {source_event_id},
            ),
            True,
        )
