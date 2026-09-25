"""Общие порты A01 без зависимости от MAX, SQLAlchemy и LLM."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RiserRef:
    riser_id: UUID
    kind: str

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("riser kind is required")


class ResidencyView(Protocol):
    @property
    def resident_id(self) -> UUID: ...

    @property
    def house_id(self) -> UUID: ...

    @property
    def entrance(self) -> int: ...

    @property
    def floor(self) -> int: ...

    @property
    def risers(self) -> frozenset[RiserRef]: ...

    @property
    def confirmed(self) -> bool: ...

    @property
    def adult(self) -> bool: ...

    @property
    def active(self) -> bool: ...

    @property
    def dm_reachable(self) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class UnitOfWork(Protocol):
    """Короткая транзакция на один use case; сеть и LLM вызываются после выхода."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object
    ) -> bool | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class HouseContextPort(Protocol):
    """A владеет реестром; потребители всегда передают доверенный house_id."""

    async def list_house_residencies(self, house_id: UUID) -> Sequence[ResidencyView]: ...

    async def resident_for_max_user(self, max_user_id: str) -> UUID | None: ...

    async def house_for_chat(self, max_chat_id: str) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class AudienceRef:
    audience_id: UUID
    house_id: UUID
    criteria_revision: int
    eligible_count: int
    reachable_count: int


@dataclass(frozen=True, slots=True)
class PollRef:
    poll_id: UUID
    house_id: UUID
    case_id: UUID
    audience_id: UUID
    subject_revision: int
    closes_at: datetime


@dataclass(frozen=True, slots=True)
class CaseRef:
    case_id: UUID
    house_id: UUID
    version: int
    workflow_status: str


@dataclass(frozen=True, slots=True)
class RequestRef:
    request_id: UUID
    case_id: UUID
    house_id: UUID
    version: int
    external_status: str


class AudiencePort(Protocol):
    async def get(self, audience_id: UUID, house_id: UUID) -> AudienceRef | None: ...


class PollPort(Protocol):
    async def get(self, poll_id: UUID, house_id: UUID) -> PollRef | None: ...


class CasePort(Protocol):
    async def get(self, case_id: UUID, house_id: UUID) -> CaseRef | None: ...

    async def transition(
        self, case_id: UUID, house_id: UUID, expected_version: int, target: str, reason: str
    ) -> CaseRef: ...


class RequestPort(Protocol):
    async def get(self, request_id: UUID, house_id: UUID) -> RequestRef | None: ...


@dataclass(frozen=True, slots=True)
class InitiativeRef:
    case_id: UUID
    house_id: UUID
    wording_revision: int
    poll_id: UUID | None


class InitiativePort(Protocol):
    async def get(self, case_id: UUID, house_id: UUID) -> InitiativeRef | None: ...


@dataclass(frozen=True, slots=True)
class DocumentRef:
    document_id: UUID
    house_id: UUID
    case_id: UUID
    status: str
    file_key: UUID | None
    snapshot_hash: str


class DocumentPort(Protocol):
    async def get(self, document_id: UUID, house_id: UUID) -> DocumentRef | None: ...


@dataclass(frozen=True, slots=True)
class ResolutionRef:
    case_id: UUID
    house_id: UUID
    poll_id: UUID | None
    outcome: str | None


class ResolutionPort(Protocol):
    async def get(self, case_id: UUID, house_id: UUID) -> ResolutionRef | None: ...


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    source_id: UUID
    revision: int
    excerpt: str


class KnowledgePort(Protocol):
    async def search(self, house_id: UUID, query: str, limit: int) -> Sequence[KnowledgeHit]: ...


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    house_id: UUID
    operation_key: str
    text: str
    recipient_id: UUID | None = None
    chat_id: str | None = None
    edit_key: str | None = None
    file_key: UUID | None = None


class DeliveryPort(Protocol):
    """Вызывается внутри UoW; возвращённый ID означает queued, не sent."""

    async def enqueue(self, intent: DeliveryIntent) -> UUID: ...


@dataclass(frozen=True, slots=True)
class JobIntent:
    house_id: UUID
    operation_key: str
    event_name: str
    due_at: datetime
    entity_id: UUID
    expected_version: int


class JobPort(Protocol):
    async def enqueue(self, intent: JobIntent) -> UUID: ...


class ExecutorPort(Protocol):
    async def get_status(self, request_id: UUID, house_id: UUID) -> RequestRef: ...


class FileStore(Protocol):
    async def get(self, house_id: UUID, file_key: UUID) -> bytes: ...
