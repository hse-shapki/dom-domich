"""Production composition callback-опроса поверх общих A/Z adapters."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.application.polls.callback import CallbackOutcome, PollCallbackHandler
from dom_domych.application.polls.max_callback import MaxPollCallbackTransport
from dom_domych.application.polls.service import PollService
from dom_domych.contracts.events import EventEnvelope, EventName
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository


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
            return await MaxPollCallbackTransport(
                session, actions, processor, self.max_client
            ).handle(event)

    async def handle(self, event: EventEnvelope) -> bool:
        await self.process(event)
        return True


def register_poll_callbacks(
    dispatcher: EventDispatcher, processor: PostgresPollCallbackProcessor
) -> None:
    dispatcher.register(EventName.CALLBACK_RECEIVED, processor.handle)
