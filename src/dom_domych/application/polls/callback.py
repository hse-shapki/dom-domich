"""Проверка сохранённого действия callback перед записью голоса жителя."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from dom_domych.application.polls.service import PollService, TrustedCallbackContext
from dom_domych.domain.polls.models import AnswerStatus, PollDefinition, VoteChoice


@dataclass(frozen=True, slots=True)
class CallbackInput:
    """Нормализованный A ingress; actor и house находятся отдельно в TrustedContext."""

    action_token: str
    source_event_id: UUID
    received_at: datetime


@dataclass(frozen=True, slots=True)
class StoredPollAction:
    """Серверная запись короткого непрозрачного токена, без личных данных в payload."""

    poll_id: UUID
    house_id: UUID
    audience_id: UUID
    subject_revision: int
    choice: VoteChoice
    expires_at: datetime
    bound_resident_id: UUID | None = None
    revoked: bool = False

    def __post_init__(self) -> None:
        if self.subject_revision <= 0:
            raise ValueError("subject_revision must be positive")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() != timedelta(
            0
        ):
            raise ValueError("expires_at must use UTC")


class CallbackStatus(StrEnum):
    RECORDED = "recorded"
    CHANGED = "changed"
    DUPLICATE = "duplicate"
    LATE = "late"
    STALE = "stale"
    NOT_ALLOWED = "not_allowed"
    UNKNOWN_ACTION = "unknown_action"


@dataclass(frozen=True, slots=True)
class CallbackOutcome:
    status: CallbackStatus
    poll_id: UUID | None = None
    poll_version: int | None = None


class PollActionStore(Protocol):
    async def get(self, token: str) -> StoredPollAction | None: ...


class PollReader(Protocol):
    async def get_definition(
        self, poll_id: UUID, house_id: UUID
    ) -> PollDefinition | None: ...


class PollCallbackHandler:
    """Не извлекает actor из payload и не предоставляет эту команду LLM."""

    def __init__(
        self, actions: PollActionStore, polls: PollReader, poll_service: PollService
    ) -> None:
        self.actions = actions
        self.polls = polls
        self.poll_service = poll_service

    async def handle(
        self, callback: CallbackInput, context: TrustedCallbackContext
    ) -> CallbackOutcome:
        """A transport преобразует статус в acknowledgement MAX без персональных деталей."""

        if (
            callback.received_at.tzinfo is None
            or callback.received_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("received_at must use UTC")
        action = await self.actions.get(callback.action_token)
        if action is None:
            return CallbackOutcome(CallbackStatus.UNKNOWN_ACTION)
        if action.house_id != context.house_id:
            return CallbackOutcome(CallbackStatus.NOT_ALLOWED)
        if (
            action.bound_resident_id is not None
            and action.bound_resident_id != context.actor_id
        ):
            return CallbackOutcome(CallbackStatus.NOT_ALLOWED)
        if action.revoked or callback.received_at >= action.expires_at:
            return CallbackOutcome(CallbackStatus.STALE, poll_id=action.poll_id)
        definition = await self.polls.get_definition(action.poll_id, context.house_id)
        if definition is None:
            return CallbackOutcome(CallbackStatus.STALE, poll_id=action.poll_id)
        if (
            definition.audience_id != action.audience_id
            or definition.subject_revision != action.subject_revision
            or definition.house_id != action.house_id
        ):
            return CallbackOutcome(CallbackStatus.STALE, poll_id=action.poll_id)
        if context.actor_id not in definition.eligible_residents:
            return CallbackOutcome(CallbackStatus.NOT_ALLOWED, poll_id=action.poll_id)

        mutation = await self.poll_service.record_answer(
            action.poll_id,
            action.choice,
            callback.source_event_id,
            callback.received_at,
            context,
        )
        result = mutation.answer_result
        if result is None:
            raise RuntimeError("record_answer did not return an answer result")
        status = {
            AnswerStatus.RECORDED: CallbackStatus.RECORDED,
            AnswerStatus.CHANGED: CallbackStatus.CHANGED,
            AnswerStatus.DUPLICATE: CallbackStatus.DUPLICATE,
            AnswerStatus.NOT_ELIGIBLE: CallbackStatus.NOT_ALLOWED,
            AnswerStatus.LATE: CallbackStatus.LATE,
            AnswerStatus.CLOSED: CallbackStatus.STALE,
        }[result.status]
        return CallbackOutcome(
            status, poll_id=action.poll_id, poll_version=result.poll_version
        )
