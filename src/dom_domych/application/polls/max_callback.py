"""MAX callback → доверенный житель дома → Z PollCallbackHandler."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import httpx
import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.application.polls.callback import (
    CallbackInput,
    CallbackOutcome,
    CallbackStatus,
    PollActionStore,
)
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError
from dom_domych.infrastructure.postgres.models import HouseRow, ResidencyRow, ResidentRow

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ResolvedCallbackContext:
    house_id: UUID
    actor_id: UUID


class CallbackProcessor(Protocol):
    async def handle(
        self, callback: CallbackInput, context: ResolvedCallbackContext
    ) -> CallbackOutcome: ...


class MaxPollCallbackTransport:
    """Payload выбирает только action; actor извлекается из подписанного MAX Update."""

    def __init__(
        self,
        session: AsyncSession,
        actions: PollActionStore,
        processor: CallbackProcessor,
        max_client: MaxApiClient,
    ) -> None:
        self.session = session
        self.actions = actions
        self.processor = processor
        self.max_client = max_client

    async def handle(self, event: EventEnvelope) -> CallbackOutcome:
        if event.source is not EventSource.MAX or event.name is not EventName.CALLBACK_RECEIVED:
            raise ValueError("MAX callback event required")
        callback = event.callback
        if callback is None or callback.sender_user_id != event.actor_user_id:
            raise ValueError("inconsistent callback actor")
        await self._acknowledge(callback.callback_id)
        action = await self.actions.get(callback.action_token)
        if action is None:
            return CallbackOutcome(CallbackStatus.UNKNOWN_ACTION)
        if callback.chat_id is not None and not callback.chat_id.startswith("dm:"):
            house_id = await self.session.scalar(
                select(HouseRow.id).where(HouseRow.max_chat_id == callback.chat_id)
            )
            if house_id != action.house_id:
                return CallbackOutcome(CallbackStatus.NOT_ALLOWED)
        actor_id = await self._resolve_resident(
            callback.sender_user_id, action.house_id, event.received_at
        )
        if actor_id is None:
            return CallbackOutcome(CallbackStatus.NOT_ALLOWED)
        return await self.processor.handle(
            CallbackInput(callback.action_token, event.event_id, event.received_at),
            ResolvedCallbackContext(action.house_id, actor_id),
        )

    async def _resolve_resident(
        self, max_user_id: str, house_id: UUID, at: datetime
    ) -> UUID | None:
        return await self.session.scalar(
            select(ResidentRow.id)
            .join(ResidencyRow, ResidencyRow.resident_id == ResidentRow.id)
            .where(
                ResidentRow.max_user_id == max_user_id,
                ResidencyRow.house_id == house_id,
                ResidencyRow.confirmed.is_(True),
                ResidencyRow.adult.is_(True),
                ResidencyRow.valid_from <= at,
                or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > at),
            )
            .limit(1)
        )

    async def _acknowledge(self, callback_id: str) -> None:
        try:
            await self.max_client.answer_callback(callback_id)
        except (MaxApiError, httpx.TransportError) as exc:
            logger.warning("max_callback_ack_failed", error=type(exc).__name__)
