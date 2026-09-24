from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from dom_domych.application.resolution.service import ResolutionService
from dom_domych.domain.executor.models import DemoOperation, ExternalStatus
from dom_domych.domain.polls.policy import demo_resolution_policy
from dom_domych.domain.resolution.models import (
    ResolutionConflict,
    ResolutionForbidden,
    ResolutionState,
    ResolutionStatus,
)
from tests.domain.test_demo_executor import draft
from tests.domain.test_poll_service import floor_audience
from tests.fakes.resolution import (
    FakeResolutionCase,
    FakeResolutionCasePort,
    FakeResolutionStore,
)
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id

CASE_ID = synthetic_id("resolution-case")
DONE_EVENT_ID = synthetic_id("resolution-done-event")


@dataclass(frozen=True)
class Context:
    house_id: UUID
    capabilities: frozenset[str]


WORKER = Context(
    HOUSE_ONE,
    frozenset({"resolution.start_from_executor", "resolution.finalize"}),
)
RESIDENT = Context(HOUSE_ONE, frozenset())


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 14, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current


def done_operation() -> DemoOperation:
    at = datetime(2026, 9, 25, 13, tzinfo=timezone.utc)
    return DemoOperation(
        operation_id=synthetic_id("done-operation"),
        operation_key="demo-submit",
        draft=draft(),
        status=ExternalStatus.DONE,
        submitted_at=at - timedelta(hours=1),
        registration_number="DEMO-ABC123",
        registered_at=at,
        status_updated_at=at,
    )


def setup() -> tuple[
    ResolutionService, FakeResolutionCasePort, FakeResolutionStore, FakeClock
]:
    case_port = FakeResolutionCasePort(
        FakeResolutionCase(
            case_id=CASE_ID,
            house_id=HOUSE_ONE,
            request_id=draft().request_id,
            original_audience_id=floor_audience().audience_id,
        )
    )
    store = FakeResolutionStore(case_port)
    clock = FakeClock()
    return ResolutionService(case_port, store, clock), case_port, store, clock


async def start(service: ResolutionService) -> ResolutionState:
    return await service.start_check(
        CASE_ID,
        done_operation(),
        DONE_EVENT_ID,
        floor_audience(),
        demo_resolution_policy(),
        timedelta(hours=2),
        WORKER,
        operation_key="start-check",
    )


@pytest.mark.asyncio
async def test_done_starts_poll_of_original_audience_without_closing_case() -> None:
    service, cases, store, _ = setup()

    first = await start(service)
    repeated = await start(service)
    poll = store.polls[first.poll_id]

    assert first == repeated
    assert first.status is ResolutionStatus.CHECKING
    assert cases.case.workflow_status == "checking_resolution"
    assert poll.tally.eligible == 12
    assert len(store.notifications[first.poll_id]) == 12
    assert first.poll_id in store.deadline_jobs
    assert store.events == [("resolution.started", CASE_ID)]


@pytest.mark.asyncio
async def test_resident_and_wrong_audience_cannot_start_check() -> None:
    service, cases, store, _ = setup()

    with pytest.raises(ResolutionForbidden):
        await service.start_check(
            CASE_ID,
            done_operation(),
            DONE_EVENT_ID,
            floor_audience(),
            demo_resolution_policy(),
            timedelta(hours=2),
            RESIDENT,
            operation_key="resident",
        )
    with pytest.raises(ResolutionForbidden, match="original audience"):
        await service.start_check(
            CASE_ID,
            done_operation(),
            DONE_EVENT_ID,
            replace(floor_audience(), audience_id=synthetic_id("new-category")),
            demo_resolution_policy(),
            timedelta(hours=2),
            WORKER,
            operation_key="new-category",
        )
    assert cases.case.workflow_status == "in_progress"
    assert store.states == {}


@pytest.mark.asyncio
async def test_empty_original_audience_still_opens_unconfirmed_check() -> None:
    service, cases, store, _ = setup()
    empty = replace(floor_audience(), members=())

    state = await service.start_check(
        CASE_ID,
        done_operation(),
        DONE_EVENT_ID,
        empty,
        demo_resolution_policy(),
        timedelta(hours=2),
        WORKER,
        operation_key="empty-audience",
    )

    assert store.polls[state.poll_id].tally.eligible == 0
    assert store.notifications[state.poll_id] == ()
    assert cases.case.workflow_status == "checking_resolution"


@pytest.mark.asyncio
async def test_unregistered_or_not_done_does_not_start_check() -> None:
    service, _, store, _ = setup()
    not_done = replace(done_operation(), status=ExternalStatus.IN_PROGRESS)

    with pytest.raises(ResolutionConflict, match="registered done"):
        await service.start_check(
            CASE_ID,
            not_done,
            DONE_EVENT_ID,
            floor_audience(),
            demo_resolution_policy(),
            timedelta(hours=2),
            WORKER,
            operation_key="not-done",
        )
    assert store.states == {}
