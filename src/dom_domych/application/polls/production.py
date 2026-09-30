"""Production composition callback-опроса поверх общих A/Z adapters."""

import httpx
import structlog
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
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.max.client import MaxApiClient, MaxApiError
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository

logger = structlog.get_logger()

_CALLBACK_NOTIFICATIONS = {
    CallbackStatus.RECORDED: "Голос учтён.",
    CallbackStatus.CHANGED: "Голос изменён.",
    CallbackStatus.DUPLICATE: "Этот голос уже учтён.",
    CallbackStatus.LATE: "Время голосования истекло.",
    CallbackStatus.CLOSED: "Опрос уже завершён.",
    CallbackStatus.STALE: "Кнопка устарела. Откройте актуальную карточку.",
    CallbackStatus.NOT_ALLOWED: "Этот опрос доступен только жителям затронутой части дома.",
    CallbackStatus.UNKNOWN_ACTION: "Кнопка устарела. Откройте актуальную карточку.",
}


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
        async with self.sessions.begin() as session:
            actions = PostgresPollActionStore(session)
            polls = PostgresPollRepository(session)
            processor = PollCallbackHandler(actions, polls, PollService(polls, self.clock))
            outcome = await MaxPollCallbackTransport(session, actions, processor).handle(event)
            if outcome.status in (CallbackStatus.RECORDED, CallbackStatus.CHANGED):
                if outcome.poll_id is None or outcome.delivery_house_id is None:
                    raise RuntimeError("recorded callback has no trusted poll context")
                await PostgresPublicCards(self.sessions, self.clock).enqueue_poll_update(
                    session, outcome.poll_id, outcome.delivery_house_id
                )
        await self._acknowledge(event, outcome)
        return outcome

    async def _acknowledge(self, event: EventEnvelope, outcome: CallbackOutcome) -> None:
        callback = event.callback
        if callback is None:
            raise ValueError("callback payload required")
        try:
            await self.max_client.answer_callback(
                callback.callback_id,
                _CALLBACK_NOTIFICATIONS[outcome.status],
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
