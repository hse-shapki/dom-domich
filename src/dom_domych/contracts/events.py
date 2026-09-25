"""Нормализованные события между MAX ingress, workers и доменными обработчиками."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from dom_domych.contracts.base import StrictContract, require_utc


class EventSource(StrEnum):
    MAX = "max"
    SCHEDULER = "scheduler"
    EXECUTOR = "executor"
    DOMAIN = "domain"


class EventName(StrEnum):
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_REMOVED = "message.removed"
    CALLBACK_RECEIVED = "callback.received"
    ATTACHMENT_RECEIVED = "attachment.received"
    POLL_THRESHOLD_REACHED = "poll.threshold_reached"
    POLL_EXPIRED = "poll.expired"
    DOCUMENT_READY = "document.ready"
    REQUEST_REGISTERED = "request.registered"
    REQUEST_STATUS_CHANGED = "request.status_changed"
    RESOLUTION_REJECTED = "resolution.rejected"
    JOB_DUE = "job.due"


class MessagePayload(StrictContract):
    chat_id: str
    message_id: str
    sender_user_id: str
    text: str | None = None
    attachment_refs: tuple[str, ...] = ()


class CallbackPayload(StrictContract):
    callback_id: str
    sender_user_id: str
    action_token: str
    chat_id: str | None = None


class EntityEventPayload(StrictContract):
    entity_id: UUID
    entity_version: int = Field(ge=1)
    case_id: UUID | None = None
    causation_id: UUID | None = None


class EventEnvelope(StrictContract):
    """Событие с ключом дедупликации; house_id может ожидать разрешения для лички."""

    event_id: UUID
    source: EventSource
    source_key: str = Field(min_length=1)
    name: EventName
    occurred_at: datetime
    received_at: datetime
    correlation_id: UUID
    house_id: UUID | None = None
    actor_user_id: str | None = None
    message: MessagePayload | None = None
    callback: CallbackPayload | None = None
    entity: EntityEventPayload | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "EventEnvelope":
        selected = sum(value is not None for value in (self.message, self.callback, self.entity))
        if selected != 1:
            raise ValueError("event requires exactly one payload")
        expected = {
            EventName.MESSAGE_RECEIVED: self.message,
            EventName.MESSAGE_REMOVED: self.message,
            EventName.ATTACHMENT_RECEIVED: self.message,
            EventName.CALLBACK_RECEIVED: self.callback,
        }
        if self.name in expected and expected[self.name] is None:
            raise ValueError("payload does not match event name")
        if self.name not in expected and self.entity is None:
            raise ValueError("domain event requires entity payload")
        return self

    @field_validator("occurred_at", "received_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("actor_user_id")
    @classmethod
    def validate_actor_id(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("actor_user_id cannot be empty")
        return value
