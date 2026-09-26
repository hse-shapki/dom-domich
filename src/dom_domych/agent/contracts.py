"""Предложение K00 для A01: команды и ответы на границе агента и дел."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import Field, model_validator

from dom_domych.contracts.base import StrictContract as StrictModel
from dom_domych.contracts.base import TrustedContext


class CaseKind(StrEnum):
    PROBLEM = "problem"
    EMERGENCY = "emergency"
    INITIATIVE = "initiative"


class CaseSearch(StrictModel):
    query: str = Field(min_length=3, max_length=500)
    entrance: int | None = Field(default=None, ge=1)
    floor: int | None = None
    object_name: str | None = Field(default=None, max_length=100)


class CaseGet(StrictModel):
    case_id: UUID


class CaseCandidate(StrictModel):
    case_id: UUID
    version: int = Field(ge=1)
    kind: CaseKind
    title: str
    entrance: int | None
    floor: int | None
    object_name: str | None
    source_refs: tuple[str, ...]


class CaseCreate(StrictModel):
    kind: CaseKind
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=2000)
    entrance: int | None = Field(default=None, ge=1)
    floor: int | None = None
    object_name: str | None = Field(default=None, max_length=100)
    source_message_id: UUID
    candidate_case_ids: tuple[UUID, ...] = ()
    operation_id: UUID


class CaseAttachMessage(StrictModel):
    case_id: UUID
    message_id: UUID
    expected_version: int = Field(ge=1)
    operation_id: UUID


class CaseView(StrictModel):
    case_id: UUID
    version: int = Field(ge=1)
    kind: CaseKind
    title: str
    status: str
    source_refs: tuple[str, ...]


class KnowledgeSearch(StrictModel):
    query: str = Field(min_length=3, max_length=500)
    topic: str | None = Field(default=None, max_length=100)


class KnowledgeHit(StrictModel):
    source_id: UUID
    revision: int = Field(ge=1)
    excerpt: str
    reviewed: bool
    rule_id: UUID | None = None
    deadline_origin: str | None = None


class RequestPrepare(StrictModel):
    case_id: UUID
    expected_case_version: int = Field(ge=1)
    responsible_id: UUID
    source_refs: tuple[str, ...] = Field(min_length=1)
    operation_id: UUID


class RequestSubmit(StrictModel):
    request_id: UUID
    expected_draft_version: int = Field(ge=1)
    operation_id: UUID


class RequestGetStatus(StrictModel):
    request_id: UUID


class EmergencyHandle(StrictModel):
    case_id: UUID
    expected_case_version: int = Field(ge=1)


class RequestView(StrictModel):
    request_id: UUID
    case_id: UUID
    draft_version: int = Field(ge=1)
    status: str
    registration_id: str | None = None
    registered_at: datetime | None = None

    @model_validator(mode="after")
    def registration_is_complete(self) -> RequestView:
        if (self.registration_id is None) != (self.registered_at is None):
            raise ValueError("Номер и время регистрации должны присутствовать вместе")
        return self


class ContinuationEvent(StrEnum):
    POLL_THRESHOLD_REACHED = "poll.threshold_reached"
    POLL_EXPIRED = "poll.expired"
    EVIDENCE_ADDED = "evidence.added"
    REQUEST_REGISTERED = "request.registered"
    REQUEST_STATUS_CHANGED = "request.status_changed"
    REQUEST_DEADLINE_REACHED = "request.deadline_reached"
    RESOLUTION_REJECTED = "resolution.rejected"
    DOCUMENT_READY = "document.ready"


class Continuation(StrictModel):
    event: ContinuationEvent
    house_id: UUID
    case_id: UUID
    case_version: int = Field(ge=1)
    event_id: UUID
    occurred_at: datetime


class CasePort(Protocol):
    """Все операции ограничены trusted house и проверяются при записи."""

    async def search(
        self, command: CaseSearch, context: TrustedContext
    ) -> tuple[CaseCandidate, ...]: ...
    async def get(self, case_id: UUID, context: TrustedContext) -> CaseView | None: ...
    async def create(self, command: CaseCreate, context: TrustedContext) -> CaseView: ...
    async def attach_message(
        self, command: CaseAttachMessage, context: TrustedContext
    ) -> CaseView: ...


class KnowledgePort(Protocol):
    async def search(
        self, command: KnowledgeSearch, context: TrustedContext
    ) -> tuple[KnowledgeHit, ...]: ...


class RequestPort(Protocol):
    async def prepare(self, command: RequestPrepare, context: TrustedContext) -> RequestView: ...
    async def submit(self, command: RequestSubmit, context: TrustedContext) -> RequestView: ...
    async def get_status(self, request_id: UUID, context: TrustedContext) -> RequestView | None: ...


class EmergencyResult(Protocol):
    @property
    def case_id(self) -> UUID: ...

    @property
    def status(self) -> str: ...

    @property
    def urgency_source_ref(self) -> str: ...

    @property
    def evidence_delivery_id(self) -> UUID: ...

    @property
    def request_id(self) -> UUID | None: ...

    @property
    def rule_source_ref(self) -> str | None: ...

    @property
    def deadline(self) -> timedelta | None: ...

    @property
    def deadline_origin(self) -> str | None: ...


class EmergencyPort(Protocol):
    async def handle(
        self, case_id: UUID, expected_case_version: int, context: TrustedContext
    ) -> EmergencyResult: ...


TOOL_INPUTS: dict[str, type[StrictModel]] = {
    "case.search": CaseSearch,
    "case.get": CaseGet,
    "case.create": CaseCreate,
    "case.attach_message": CaseAttachMessage,
    "knowledge.search": KnowledgeSearch,
    "request.prepare": RequestPrepare,
    "request.submit": RequestSubmit,
    "request.get_status": RequestGetStatus,
    "emergency.handle": EmergencyHandle,
}
