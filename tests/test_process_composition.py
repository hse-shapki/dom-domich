from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.llm import FakeLlmPort
from dom_domych.application.jobs.inbox_worker import SystemClock
from dom_domych.contracts.events import EventName
from dom_domych.entrypoints.processes import _k_runtime


def test_k_runtime_registers_mutation_before_continuation_handlers() -> None:
    sessions = async_sessionmaker[AsyncSession]()

    dispatcher, _ = _k_runtime(sessions, FakeLlmPort([]), SystemClock())

    assert len(dispatcher.handlers[EventName.REQUEST_STATUS_CHANGED]) == 3
    assert len(dispatcher.handlers[EventName.DOCUMENT_READY]) == 3
    assert EventName.POLL_EXPIRED in dispatcher.handlers
    assert EventName.REQUEST_DEADLINE_REACHED in dispatcher.handlers
