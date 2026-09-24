"""Неизменяемые факты документа; PDF-рендер не обращается к живой БД."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from dom_domych.domain.polls.policy import VoteTally


class DocumentKind(StrEnum):
    APPEAL = "appeal"
    RESIDENT_POSITION = "resident_position"
    NOTIFICATION_REGISTER = "notification_register"
    COMPLAINT_DRAFT = "complaint_draft"


class DocumentMode(StrEnum):
    DEMO = "demo"
    LIVE_DRAFT = "live_draft"


class NoticeStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERY_UNKNOWN = "delivery_unknown"


@dataclass(frozen=True, slots=True)
class DocumentFact:
    key: str
    value: str
    source_ref: str

    def __post_init__(self) -> None:
        if not self.key or not self.value or not self.source_ref:
            raise ValueError("document fact needs key, value and source")


@dataclass(frozen=True, slots=True)
class NoticeEntry:
    resident_id: UUID
    status: NoticeStatus
    attempted_at: datetime | None
    delivery_operation_id: UUID | None

    def __post_init__(self) -> None:
        if self.attempted_at is not None and (
            self.attempted_at.tzinfo is None
            or self.attempted_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("attempted_at must use UTC")


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    kind: DocumentKind
    mode: DocumentMode
    template_revision: str
    house_id: UUID
    case_id: UUID
    case_revision: int
    audience_id: UUID
    audience_revision: int
    poll_id: UUID | None
    poll_revision: int | None
    request_id: UUID | None
    request_revision: int | None
    title: str
    house_address: str
    facts: tuple[DocumentFact, ...]
    tally: VoteTally | None
    notices: tuple[NoticeEntry, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.case_revision <= 0 or self.audience_revision <= 0:
            raise ValueError("case and audience revisions must be positive")
        if (self.poll_id is None) != (self.poll_revision is None):
            raise ValueError("poll ID and revision must be set together")
        if (self.request_id is None) != (self.request_revision is None):
            raise ValueError("request ID and revision must be set together")
        if self.poll_revision is not None and self.poll_revision <= 0:
            raise ValueError("poll revision must be positive")
        if self.request_revision is not None and self.request_revision <= 0:
            raise ValueError("request revision must be positive")
        if not self.template_revision or not self.title or not self.house_address:
            raise ValueError("template revision, title and address are required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(
            0
        ):
            raise ValueError("created_at must use UTC")
        if self.tally is not None and self.poll_id is None:
            raise ValueError("vote tally needs a poll reference")
        if len({item.resident_id for item in self.notices}) != len(self.notices):
            raise ValueError("notice register cannot repeat a resident")

    def canonical_bytes(self) -> bytes:
        """Стабильное представление привязывает PDF и согласование к одной ревизии фактов."""

        payload = {
            "kind": self.kind.value,
            "mode": self.mode.value,
            "template_revision": self.template_revision,
            "house_id": str(self.house_id),
            "case_id": str(self.case_id),
            "case_revision": self.case_revision,
            "audience_id": str(self.audience_id),
            "audience_revision": self.audience_revision,
            "poll_id": str(self.poll_id) if self.poll_id is not None else None,
            "poll_revision": self.poll_revision,
            "request_id": str(self.request_id) if self.request_id is not None else None,
            "request_revision": self.request_revision,
            "title": self.title,
            "house_address": self.house_address,
            "facts": [
                {"key": item.key, "value": item.value, "source_ref": item.source_ref}
                for item in self.facts
            ],
            "tally": (
                {
                    "eligible": self.tally.eligible,
                    "yes": self.tally.yes,
                    "no": self.tally.no,
                }
                if self.tally is not None
                else None
            ),
            "notices": [
                {
                    "resident_id": str(item.resident_id),
                    "status": item.status.value,
                    "attempted_at": item.attempted_at.isoformat()
                    if item.attempted_at is not None
                    else None,
                    "delivery_operation_id": str(item.delivery_operation_id)
                    if item.delivery_operation_id is not None
                    else None,
                }
                for item in self.notices
            ],
            "created_at": self.created_at.isoformat(),
        }
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
