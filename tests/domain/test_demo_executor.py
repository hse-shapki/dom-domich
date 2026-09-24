import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.domain.executor.models import (
    ApprovedDraft,
    ExecutorConflict,
    ExecutorForbidden,
    ExecutorNotFound,
    ExternalStatus,
)
from tests.fakes.executor import FakeExecutorStore
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, synthetic_id


@dataclass(frozen=True)
class Context:
    house_id: UUID
    capabilities: frozenset[str]


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 14, tzinfo=timezone.utc)


def draft() -> ApprovedDraft:
    return ApprovedDraft(
        house_id=HOUSE_ONE,
        request_id=synthetic_id("request-1"),
        draft_id=synthetic_id("draft-1"),
        draft_revision=2,
        content_sha256="a" * 64,
    )


SUBMIT = Context(HOUSE_ONE, frozenset({"demo_executor.submit"}))
REGISTER = Context(HOUSE_ONE, frozenset({"demo_executor.register"}))
OPERATOR = Context(HOUSE_ONE, frozenset({"demo_executor.operator"}))
RESIDENT = Context(HOUSE_ONE, frozenset())


@pytest.mark.asyncio
async def test_submit_and_register_are_idempotent_with_demo_provenance() -> None:
    store = FakeExecutorStore()
    service = DemoExecutorService(store, FakeClock())

    first, second = await asyncio.gather(
        service.submit(draft(), "request-1-v2", SUBMIT),
        service.submit(draft(), "request-1-v2", SUBMIT),
    )
    registered, emitted = await service.register(first.operation_id, REGISTER)
    again, emitted_again = await service.register(first.operation_id, REGISTER)

    assert first == second
    assert emitted is True
    assert emitted_again is False
    assert again == registered
    assert registered.status is ExternalStatus.REGISTERED
    assert registered.registration_number is not None
    assert registered.registration_number.startswith("DEMO-")
    assert registered.source == "demo_executor"
    assert store.events.count(("request.registered", first.operation_id)) == 1


@pytest.mark.asyncio
async def test_same_operation_key_cannot_submit_changed_draft() -> None:
    service = DemoExecutorService(FakeExecutorStore(), FakeClock())
    await service.submit(draft(), "request-1-v2", SUBMIT)

    with pytest.raises(ExecutorConflict, match="another draft"):
        await service.submit(replace(draft(), draft_revision=3), "request-1-v2", SUBMIT)

    with pytest.raises(ExecutorConflict, match="already has"):
        await service.submit(draft(), "second-key", SUBMIT)


@pytest.mark.asyncio
async def test_resident_cannot_submit_register_or_mark_done() -> None:
    service = DemoExecutorService(FakeExecutorStore(), FakeClock())
    operation = await service.submit(draft(), "request-1-v2", SUBMIT)

    with pytest.raises(ExecutorForbidden):
        await service.submit(draft(), "other-key", RESIDENT)
    with pytest.raises(ExecutorForbidden):
        await service.register(operation.operation_id, RESIDENT)
    with pytest.raises(ExecutorForbidden):
        await service.set_status(
            operation.operation_id,
            ExternalStatus.DONE,
            synthetic_id("event-1"),
            RESIDENT,
        )


@pytest.mark.asyncio
async def test_done_is_external_status_only_and_duplicate_event_is_ignored() -> None:
    store = FakeExecutorStore()
    service = DemoExecutorService(store, FakeClock())
    operation = await service.submit(draft(), "request-1-v2", SUBMIT)
    await service.register(operation.operation_id, REGISTER)
    event_id = synthetic_id("done-event")

    done, emitted = await service.set_status(
        operation.operation_id, ExternalStatus.DONE, event_id, OPERATOR
    )
    repeated, emitted_again = await service.set_status(
        operation.operation_id, ExternalStatus.DONE, event_id, OPERATOR
    )

    assert emitted is True
    assert emitted_again is False
    assert repeated == done
    assert done.status is ExternalStatus.DONE
    assert not hasattr(done, "workflow_status")
    assert store.events.count(("request.status_changed", operation.operation_id)) == 1


@pytest.mark.asyncio
async def test_wrong_house_cannot_read_or_change_operation() -> None:
    service = DemoExecutorService(FakeExecutorStore(), FakeClock())
    operation = await service.submit(draft(), "request-1-v2", SUBMIT)
    wrong_house = Context(HOUSE_TWO, OPERATOR.capabilities | REGISTER.capabilities)

    with pytest.raises(ExecutorNotFound):
        await service.get_status(draft().request_id, wrong_house)
    with pytest.raises(ExecutorNotFound):
        await service.register(operation.operation_id, wrong_house)
    with pytest.raises(ExecutorNotFound):
        await service.set_status(
            operation.operation_id,
            ExternalStatus.DONE,
            synthetic_id("other-house-event"),
            wrong_house,
        )


@pytest.mark.asyncio
async def test_invalid_status_transition_is_rejected() -> None:
    service = DemoExecutorService(FakeExecutorStore(), FakeClock())
    operation = await service.submit(draft(), "request-1-v2", SUBMIT)

    with pytest.raises(ExecutorConflict):
        await service.set_status(
            operation.operation_id,
            ExternalStatus.DONE,
            synthetic_id("early-done"),
            OPERATOR,
        )


@pytest.mark.asyncio
async def test_concurrent_different_keys_cannot_register_same_request_twice() -> None:
    store = FakeExecutorStore()
    service = DemoExecutorService(store, FakeClock())
    outcomes = await asyncio.gather(
        service.submit(draft(), "first-key", SUBMIT),
        service.submit(draft(), "second-key", SUBMIT),
        return_exceptions=True,
    )

    assert len([item for item in outcomes if isinstance(item, ExecutorConflict)]) == 1
    assert len([item for item in outcomes if not isinstance(item, BaseException)]) == 1
    assert (
        len([event for event in store.events if event[0] == "request.submitted"]) == 1
    )


def test_approved_draft_requires_hex_sha256() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        replace(draft(), content_sha256="z" * 64)
