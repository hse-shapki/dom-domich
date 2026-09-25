"""Базовые идентификаторы, версии и доверенный контекст исполнения."""

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def require_utc(value: datetime) -> datetime:
    """Отклоняет naive и не-UTC время на границе приложения."""

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use aware UTC")
    return value


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PrincipalType(StrEnum):
    RESIDENT = "resident"
    BOT = "bot"
    WORKER = "worker"
    DEMO_OPERATOR = "demo_operator"


class ExecutionMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class TrustedContext(StrictContract):
    """Создаётся ingress/worker по проверенному событию; модель не может его подменить."""

    run_id: UUID
    event_id: UUID
    house_id: UUID
    actor_id: UUID | None
    principal_type: PrincipalType
    capabilities: frozenset[str] = Field(default_factory=frozenset)
    correlation_id: UUID
    mode: ExecutionMode
    case_id: UUID | None = None
    deadline: datetime | None = None

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None


class EntityRef(StrictContract):
    entity_id: UUID
    version: int = Field(ge=1)
