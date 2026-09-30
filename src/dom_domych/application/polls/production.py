"""Production composition callback-опроса поверх общих A/Z adapters."""

from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.cards.production import PostgresPublicCards
from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.polls.callback import (
    CallbackOutcome,
    CallbackStatus,
    PollCallbackHandler,
)
from dom_domych.application.polls.max_callback import MaxPollCallbackTransport
from dom_domych.application.polls.service import PollService
from dom_domych.contracts.events import EventEnvelope, EventName
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import OutboxDeliveryRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository

logger = structlog.get_logger()

_CALLBACK_NOTIFICATIONS = {
    CallbackStatus.LATE: "Время голосования истекло.",
    CallbackStatus.CLOSED: "Опрос уже завершён.",
    CallbackStatus.STALE: "Кнопка устарела. Откройте актуальную карточку.",
    CallbackStatus.NOT_ALLOWED: "Этот опрос доступен только жителям затронутой части дома.",
    CallbackStatus.UNKNOWN_ACTION: "Кнопка устарела. Откройте актуальную карточку.",
}


def _choice_message(kind: PollKind, choice: VoteChoice) -> str:
    messages = {
        PollKind.PROBLEM_CONFIRMATION: ("Вы подтвердили проблему.", "Вы не подтвердили проблему."),
        PollKind.INITIATIVE_POSITION: ("Вы поддержали инициативу.", "Вы не поддержали инициативу."),
        PollKind.RESOLUTION_CHECK: ("Вы подтвердили выполнение.", "Вы не подтвердили выполнение."),
    }
    return messages[kind][0 if choice is VoteChoice.YES else 1]


class PostgresPollCallbackProcessor:
    """Коммитит проверенный голос, историю и событие порога одной транзакцией."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        max_client: MaxApiClient,
        clock: Clock,
    ) -> None:
        self.sessions = sessions
        self.max_client = max_client
        self.clock = clock

    async def process(self, event: EventEnvelope) -> CallbackOutcome:
        personal_choice: str | None = None
        async with self.sessions.begin() as session:
            actions = PostgresPollActionStore(session)
            polls = PostgresPollRepository(session)
            processor = PollCallbackHandler(actions, polls, PollService(polls, self.clock))
            outcome = await MaxPollCallbackTransport(session, actions, processor).handle(event)
            if (
                outcome.status
                in {CallbackStatus.RECORDED, CallbackStatus.CHANGED, CallbackStatus.DUPLICATE}
                and outcome.poll_id is not None
                and outcome.poll_version is not None
                and outcome.recipient_id is not None
                and outcome.delivery_house_id is not None
            ):
                state = await polls.get_state(outcome.poll_id, outcome.delivery_house_id)
                if state is None:
                    raise RuntimeError("recorded callback poll disappeared")
                answer = next(
                    (item for item in state.answers if item.resident_id == outcome.recipient_id),
                    None,
                )
                if answer is None:
                    raise RuntimeError("recorded callback answer disappeared")
                personal_choice = _choice_message(state.definition.kind, answer.choice)
                await self._enqueue_personal_choice(
                    session,
                    outcome.poll_id,
                    outcome.poll_version,
                    outcome.recipient_id,
                    outcome.delivery_house_id,
                    state.definition.kind,
                    personal_choice,
                )
            if outcome.status in (CallbackStatus.RECORDED, CallbackStatus.CHANGED):
                if outcome.poll_id is None or outcome.delivery_house_id is None:
                    raise RuntimeError("recorded callback has no trusted poll context")
                await PostgresPublicCards(self.sessions, self.clock).enqueue_poll_update(
                    session, outcome.poll_id, outcome.delivery_house_id
                )
        await self._acknowledge(event, outcome, personal_choice)
        return outcome

    async def _enqueue_personal_choice(
        self,
        session: AsyncSession,
        poll_id: UUID,
        poll_version: int,
        resident_id: UUID,
        house_id: UUID,
        kind: PollKind,
        choice_message: str,
    ) -> None:
        prefix = "resolution:check" if kind is PollKind.RESOLUTION_CHECK else "poll:invite"
        edit_key = f"{prefix}:{poll_id}:{resident_id}"
        base = await session.scalar(
            select(OutboxDeliveryRow).where(
                OutboxDeliveryRow.house_id == house_id,
                OutboxDeliveryRow.operation_key == edit_key,
            )
        )
        if base is None:
            return
        original = base.text.split("\n\n✅ ", 1)[0]
        await PostgresDeliveryQueue(session, self.clock).enqueue(
            DeliveryIntent(
                house_id=house_id,
                operation_key=(f"poll:invite-choice:{poll_id}:{resident_id}:{poll_version}"),
                text=f"{original}\n\n✅ {choice_message}",
                recipient_id=resident_id,
                edit_key=edit_key,
                buttons=(),
            )
        )

    async def _acknowledge(
        self, event: EventEnvelope, outcome: CallbackOutcome, personal_choice: str | None
    ) -> None:
        callback = event.callback
        if callback is None:
            raise ValueError("callback payload required")
        notification = personal_choice or _CALLBACK_NOTIFICATIONS.get(
            outcome.status, "Кнопка устарела. Откройте актуальный опрос."
        )
        try:
            await self.max_client.answer_callback(
                callback.callback_id,
                notification,
                dialog_key=callback.chat_id or f"user:{callback.sender_user_id}",
            )
        except (MaxApiError, httpx.TransportError) as exc:
            logger.warning(
                "max_callback_ack_failed",
                error=type(exc).__name__,
                status_code=exc.status_code if isinstance(exc, MaxApiError) else None,
                code=exc.code if isinstance(exc, MaxApiError) else None,
            )

    async def handle(self, event: EventEnvelope) -> bool:
        await self.process(event)
        return True


def register_poll_callbacks(
    dispatcher: EventDispatcher, processor: PostgresPollCallbackProcessor
) -> None:
    dispatcher.register(EventName.CALLBACK_RECEIVED, processor.handle)
