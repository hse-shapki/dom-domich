from datetime import UTC, datetime, timedelta

import pytest

from dom_domych.application.initiatives.followup import (
    InitiativeFollowupService,
    demo_reminder_policy,
)
from dom_domych.domain.initiatives.models import InitiativeConflict
from dom_domych.domain.polls.models import PollState, VoteChoice
from dom_domych.domain.polls.policy import InitiativeOutcome
from tests.domain.test_initiative_service import create, setup
from tests.fakes.initiative_followup import FakeCurrentRights, FakeFollowupRepository
from tests.fixtures.zamira_house import synthetic_id


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 13, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


def answer(poll: PollState, number: int, choice: VoteChoice) -> PollState:
    return poll.record_answer(
        synthetic_id(f"resident-{number}"),
        choice,
        synthetic_id(f"followup-answer-{number}"),
        poll.definition.opens_at + timedelta(minutes=1),
    ).state


@pytest.mark.asyncio
async def test_reminders_only_target_currently_reachable_nonrespondents() -> None:
    initiative, initiatives = setup()
    state = await create(initiative)
    poll_id = state.current.poll_id
    initiatives.polls[poll_id] = answer(initiatives.polls[poll_id], 1, VoteChoice.YES)
    clock = FakeClock()
    allowed = {synthetic_id(f"resident-{number}") for number in range(1, 12)}
    store = FakeFollowupRepository(initiatives.polls)
    followup = InitiativeFollowupService(store, FakeCurrentRights(allowed), clock)

    targets = await followup.plan_reminders(
        state,
        initiatives.polls[poll_id],
        demo_reminder_policy(),
        operation_key="first-reminder",
    )

    assert len(targets) == 10
    assert synthetic_id("resident-1") not in targets
    assert synthetic_id("resident-12") not in targets
    assert initiatives.polls[poll_id].tally.eligible == 12
    assert len(store.outbox) == 10


@pytest.mark.asyncio
async def test_reminder_frequency_limit_and_operation_key() -> None:
    initiative, initiatives = setup()
    state = await create(initiative)
    poll = initiatives.polls[state.current.poll_id]
    rights = FakeCurrentRights(set(poll.definition.eligible_residents))
    store = FakeFollowupRepository(initiatives.polls)
    clock = FakeClock()
    followup = InitiativeFollowupService(store, rights, clock)
    policy = demo_reminder_policy()

    first = await followup.plan_reminders(state, poll, policy, operation_key="first")
    repeated = await followup.plan_reminders(state, poll, policy, operation_key="first")
    too_soon = await followup.plan_reminders(state, poll, policy, operation_key="soon")
    clock.current += timedelta(minutes=31)
    second = await followup.plan_reminders(state, poll, policy, operation_key="second")
    clock.current += timedelta(minutes=31)
    capped = await followup.plan_reminders(state, poll, policy, operation_key="third")

    assert len(first) == 12
    assert repeated == first
    assert too_soon == ()
    assert len(second) == 12
    assert capped == ()
    assert len(store.outbox) == 24


@pytest.mark.asyncio
async def test_supported_position_emits_only_supported_event_after_finalization() -> None:
    initiative, initiatives = setup()
    state = await create(initiative)
    poll = initiatives.polls[state.current.poll_id]
    for number in range(1, 8):
        poll = answer(poll, number, VoteChoice.YES if number <= 5 else VoteChoice.NO)
    poll = poll.finalize(poll.definition.closes_at).state
    initiatives.polls[state.current.poll_id] = poll
    store = FakeFollowupRepository(initiatives.polls)
    followup = InitiativeFollowupService(store, FakeCurrentRights(set()), FakeClock())

    first = await followup.finalize_position(state, poll, operation_key="decision")
    repeated = await followup.finalize_position(state, poll, operation_key="decision")

    assert first == repeated
    assert first.outcome is InitiativeOutcome.SUPPORTED
    assert first.policy_revision == "demo-initiative-v1"
    assert store.events == [("initiative.supported", state.case_id)]


@pytest.mark.asyncio
async def test_insufficient_participation_never_emits_supported() -> None:
    initiative, initiatives = setup()
    state = await create(initiative)
    poll = answer(initiatives.polls[state.current.poll_id], 1, VoteChoice.YES)
    poll = poll.finalize(poll.definition.closes_at).state
    initiatives.polls[state.current.poll_id] = poll
    store = FakeFollowupRepository(initiatives.polls)
    followup = InitiativeFollowupService(store, FakeCurrentRights(set()), FakeClock())

    decision = await followup.finalize_position(state, poll, operation_key="decision")

    assert decision.outcome is InitiativeOutcome.NOT_SUPPORTED
    assert store.events == [("initiative.not_supported", state.case_id)]


@pytest.mark.asyncio
async def test_open_poll_cannot_be_decided_or_reminded_after_deadline() -> None:
    initiative, initiatives = setup()
    state = await create(initiative)
    poll = initiatives.polls[state.current.poll_id]
    store = FakeFollowupRepository(initiatives.polls)
    clock = FakeClock()
    followup = InitiativeFollowupService(
        store, FakeCurrentRights(set(poll.definition.eligible_residents)), clock
    )

    with pytest.raises(InitiativeConflict, match="not finalized"):
        await followup.finalize_position(state, poll, operation_key="premature")
    clock.current = poll.definition.closes_at - timedelta(minutes=4)
    assert (
        await followup.plan_reminders(
            state, poll, demo_reminder_policy(), operation_key="late-reminder"
        )
        == ()
    )
    assert store.events == []
