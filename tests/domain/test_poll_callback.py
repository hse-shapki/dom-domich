from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from dom_domych.application.polls.callback import (
    CallbackInput,
    CallbackStatus,
    PollCallbackHandler,
    StoredPollAction,
)
from dom_domych.application.polls.service import PollService
from dom_domych.domain.audiences.models import (
    AudienceMember,
    AudienceScope,
    AudienceSnapshot,
    ScopeKind,
)
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.polls.policy import demo_initiative_policy
from tests.fakes.polls import FakePollRepository
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, synthetic_id


@dataclass(frozen=True, slots=True)
class FakeContext:
    house_id: UUID
    actor_id: UUID


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


class FakeActionStore:
    def __init__(self, action: StoredPollAction) -> None:
        self.actions = {"opaque-token": action}

    async def get(self, token: str) -> StoredPollAction | None:
        return self.actions.get(token)


async def setup_callback() -> tuple[
    PollCallbackHandler, FakeActionStore, FakePollRepository, UUID, datetime
]:
    clock = FakeClock()
    repository = FakePollRepository()
    service = PollService(repository, clock)
    audience = AudienceSnapshot(
        audience_id=synthetic_id("callback-audience"),
        house_id=HOUSE_ONE,
        scope=AudienceScope(kind=ScopeKind.HOUSE),
        criteria_revision=1,
        members=tuple(
            AudienceMember(synthetic_id(f"resident-{number}"), True) for number in (1, 2, 3)
        ),
        created_at=clock.now(),
    )
    poll = await service.open(
        synthetic_id("callback-case"),
        audience,
        PollKind.INITIATIVE_POSITION,
        demo_initiative_policy(),
        1,
        FakeContext(HOUSE_ONE, synthetic_id("resident-1")),
        operation_key="callback-open",
        window=timedelta(hours=24),
    )
    action = StoredPollAction(
        poll_id=poll.definition.poll_id,
        house_id=HOUSE_ONE,
        audience_id=audience.audience_id,
        subject_revision=1,
        choice=VoteChoice.YES,
        expires_at=clock.now() + timedelta(hours=25),
    )
    store = FakeActionStore(action)
    return (
        PollCallbackHandler(store, repository, service),
        store,
        repository,
        action.poll_id,
        clock.now(),
    )


def callback(event_name: str, received_at: datetime) -> CallbackInput:
    return CallbackInput(
        action_token="opaque-token",
        source_event_id=synthetic_id(event_name),
        received_at=received_at,
    )


@pytest.mark.asyncio
async def test_callback_records_one_answer_from_real_actor_and_acknowledges_repeat() -> None:
    handler, _, repository, poll_id, now = await setup_callback()
    actor = FakeContext(HOUSE_ONE, synthetic_id("resident-1"))
    update = callback("callback-one", now)

    first = await handler.handle(update, actor)
    repeated = await handler.handle(update, actor)

    assert first.status == CallbackStatus.RECORDED
    assert repeated.status == CallbackStatus.DUPLICATE
    assert repository.by_id[poll_id].tally.yes == 1
    assert repository.by_id[poll_id].tally.answered == 1


@pytest.mark.asyncio
async def test_callback_rejects_unknown_token_and_wrong_house() -> None:
    handler, _, repository, poll_id, now = await setup_callback()

    unknown = await handler.handle(
        replace(callback("unknown", now), action_token="not-in-server-store"),
        FakeContext(HOUSE_ONE, synthetic_id("resident-1")),
    )
    wrong_house = await handler.handle(
        callback("wrong-house", now),
        FakeContext(HOUSE_TWO, synthetic_id("resident-1")),
    )

    assert unknown.status == CallbackStatus.UNKNOWN_ACTION
    assert wrong_house.status == CallbackStatus.NOT_ALLOWED
    assert repository.by_id[poll_id].tally.answered == 0


@pytest.mark.asyncio
async def test_personal_action_checks_bound_resident_and_membership() -> None:
    handler, store, repository, poll_id, now = await setup_callback()
    store.actions["opaque-token"] = replace(
        store.actions["opaque-token"], bound_resident_id=synthetic_id("resident-1")
    )

    wrong_recipient = await handler.handle(
        callback("bound-wrong", now), FakeContext(HOUSE_ONE, synthetic_id("resident-2"))
    )
    store.actions["opaque-token"] = replace(store.actions["opaque-token"], bound_resident_id=None)
    outsider = await handler.handle(
        callback("outsider", now), FakeContext(HOUSE_ONE, synthetic_id("resident-19"))
    )

    assert wrong_recipient.status == CallbackStatus.NOT_ALLOWED
    assert outsider.status == CallbackStatus.NOT_ALLOWED
    assert repository.by_id[poll_id].tally.answered == 0


@pytest.mark.asyncio
async def test_stale_revision_revocation_and_expiry_reject_callback() -> None:
    handler, store, repository, poll_id, now = await setup_callback()
    actor = FakeContext(HOUSE_ONE, synthetic_id("resident-1"))
    original = store.actions["opaque-token"]

    store.actions["opaque-token"] = replace(original, subject_revision=2)
    stale_revision = await handler.handle(callback("stale", now), actor)
    store.actions["opaque-token"] = replace(original, revoked=True)
    revoked = await handler.handle(callback("revoked", now), actor)
    store.actions["opaque-token"] = replace(original, expires_at=now)
    expired = await handler.handle(callback("expired", now), actor)

    assert stale_revision.status == CallbackStatus.STALE
    assert revoked.status == CallbackStatus.STALE
    assert expired.status == CallbackStatus.STALE
    assert repository.by_id[poll_id].tally.answered == 0


@pytest.mark.asyncio
async def test_callback_at_poll_deadline_is_late() -> None:
    handler, _, repository, poll_id, _ = await setup_callback()
    deadline = repository.by_id[poll_id].definition.closes_at

    result = await handler.handle(
        callback("late-event", deadline),
        FakeContext(HOUSE_ONE, synthetic_id("resident-1")),
    )

    assert result.status == CallbackStatus.LATE
    assert repository.by_id[poll_id].tally.answered == 0
