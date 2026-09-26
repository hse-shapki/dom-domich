from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.llm import FakeLlmPort
from dom_domych.application.jobs.inbox_worker import SystemClock
from dom_domych.contracts.events import EventName
from dom_domych.domain.executor.models import ApprovedDraft
from dom_domych.entrypoints.processes import _k_runtime, _UnavailableZPorts


def test_k_runtime_registers_mutation_before_continuation_handlers() -> None:
    sessions = async_sessionmaker[AsyncSession]()

    dispatcher, _ = _k_runtime(sessions, FakeLlmPort([]), SystemClock())

    assert len(dispatcher.handlers[EventName.REQUEST_STATUS_CHANGED]) == 2
    assert len(dispatcher.handlers[EventName.DOCUMENT_READY]) == 2
    assert EventName.REQUEST_DEADLINE_REACHED in dispatcher.handlers


@pytest.mark.asyncio
async def test_missing_z_ports_fail_explicitly() -> None:
    unavailable = _UnavailableZPorts()
    house_id, request_id = uuid4(), uuid4()
    draft = ApprovedDraft(house_id, request_id, uuid4(), 1, "a" * 64)

    with pytest.raises(RuntimeError, match="Z_EXECUTOR_NOT_CONFIGURED"):
        await unavailable.submit(draft, "operation", house_id)
    with pytest.raises(RuntimeError, match="Z_EXECUTOR_NOT_CONFIGURED"):
        await unavailable.get_status(request_id, house_id)
    with pytest.raises(RuntimeError, match="Z_DOCUMENT_REPOSITORY_NOT_CONFIGURED"):
        await unavailable.get(uuid4(), house_id)
