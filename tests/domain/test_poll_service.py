import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from dom_domych.application.polls.service import PollService
from dom_domych.domain.audiences.models import (
    AudienceMember,
    AudienceScope,
    AudienceSnapshot,
    ScopeKind,
)
from dom_domych.domain.polls.models import (
    AnswerStatus,
    PollKind,
    PollStatus,
    VoteChoice,
)
from dom_domych.domain.polls.policy import (
    InitiativeOutcome,
    ProblemOutcome,
    ProblemPolicy,
    ResolutionOutcome,
    demo_initiative_policy,
    demo_problem_policy,
    demo_resolution_policy,
)
from tests.fakes.polls import FakePollRepository
from tests.fixtures.zamira_house import (
    HOUSE_ONE,
    HOUSE_TWO,
    synthetic_id,
    zamira_fixture,
)


@dataclass(frozen=True, slots=True)
class FakeContext:
    house_id: UUID
    actor_id: UUID


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current


def floor_audience() -> AudienceSnapshot:
    fixture = zamira_fixture()
    residencies = (
        item
        for item in fixture.residencies
        if item.house_id == HOUSE_ONE
        and item.entrance == 2
        and item.floor == 5
        and item.confirmed
        and item.adult
        and item.active
    )
    return AudienceSnapshot(
        audience_id=synthetic_id("floor-audience"),
        house_id=HOUSE_ONE,
        scope=AudienceScope(kind=ScopeKind.FLOOR, entrance=2, floor=5),
        criteria_revision=1,
        members=tuple(
            AudienceMember(item.resident_id, item.dm_reachable) for item in residencies
        ),
        created_at=fixture.opened_at,
    )


def setup() -> tuple[PollService, FakePollRepository, FakeClock]:
    repository = FakePollRepository()
    clock = FakeClock()
    return PollService(repository, clock), repository, clock


def context(number: int, *, house_id: UUID = HOUSE_ONE) -> FakeContext:
    return FakeContext(house_id=house_id, actor_id=synthetic_id(f"resident-{number}"))


@pytest.mark.asyncio
async def test_open_freezes_all_eligible_members_and_creates_one_job() -> None:
    service, repository, clock = setup()
    audience = floor_audience()

    poll = await service.open(
        synthetic_id("case-one"),
        audience,
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="open-case-one",
    )
    repeated = await service.open(
        synthetic_id("case-one"),
        audience,
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="open-case-one",
    )

    assert poll.definition.eligible_residents == {
        item.resident_id for item in audience.members
    }
    assert poll.definition.closes_at == clock.now() + timedelta(hours=5)
    assert len(repository.notification_targets[poll.definition.poll_id]) == 12
    assert audience.reachable_count == 11
    assert repository.deadlines[poll.definition.poll_id] == poll.definition.closes_at
    assert repeated.definition.poll_id == poll.definition.poll_id
    assert len(repository.by_id) == 1


@pytest.mark.asyncio
async def test_open_rejects_duplicate_subject_or_changed_policy_for_same_key() -> None:
    service, repository, _ = setup()
    audience = floor_audience()
    case_id = synthetic_id("case-duplicate")
    await service.open(
        case_id,
        audience,
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="original-key",
    )

    with pytest.raises(ValueError, match="already opened"):
        await service.open(
            case_id,
            audience,
            PollKind.PROBLEM_CONFIRMATION,
            demo_problem_policy(),
            1,
            context(1),
            operation_key="second-key",
        )
    changed_policy = ProblemPolicy(
        revision="other-policy",
        threshold_ratio=demo_problem_policy().threshold_ratio,
        wait_period=demo_problem_policy().wait_period,
        demo=True,
    )
    with pytest.raises(ValueError, match="operation key conflicts"):
        await service.open(
            case_id,
            audience,
            PollKind.PROBLEM_CONFIRMATION,
            changed_policy,
            1,
            context(1),
            operation_key="original-key",
        )
    assert len(repository.by_id) == 1


@pytest.mark.asyncio
async def test_repeated_clicks_do_not_create_more_votes() -> None:
    service, repository, clock = setup()
    poll = await service.open(
        synthetic_id("case-two"),
        floor_audience(),
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="open-case-two",
    )

    statuses = []
    for number in range(12):
        result = await service.record_answer(
            poll.definition.poll_id,
            VoteChoice.YES,
            synthetic_id(f"repeat-event-{number}"),
            clock.now() + timedelta(minutes=number),
            context(1),
        )
        assert result.answer_result is not None
        statuses.append(result.answer_result.status)

    current = repository.by_id[poll.definition.poll_id]
    assert statuses == [AnswerStatus.RECORDED] + [AnswerStatus.DUPLICATE] * 11
    assert current.tally.yes == 1
    assert len(current.answer_history) == 1
    assert repository.events == []


@pytest.mark.asyncio
async def test_answer_change_has_history_and_old_event_replay_does_not_revert_it() -> (
    None
):
    service, repository, clock = setup()
    poll = await service.open(
        synthetic_id("initiative-one"),
        floor_audience(),
        PollKind.INITIATIVE_POSITION,
        demo_initiative_policy(),
        1,
        context(1),
        operation_key="open-initiative-one",
        window=timedelta(hours=24),
    )
    poll_id = poll.definition.poll_id
    first_event = synthetic_id("first-vote")
    await service.record_answer(
        poll_id, VoteChoice.YES, first_event, clock.now(), context(1)
    )
    changed = await service.record_answer(
        poll_id, VoteChoice.NO, synthetic_id("changed-vote"), clock.now(), context(1)
    )
    replay = await service.record_answer(
        poll_id, VoteChoice.YES, first_event, clock.now(), context(1)
    )

    current = repository.by_id[poll_id]
    assert changed.answer_result is not None
    assert changed.answer_result.status == AnswerStatus.CHANGED
    assert replay.answer_result is not None
    assert replay.answer_result.status == AnswerStatus.DUPLICATE
    assert current.tally.yes == 0 and current.tally.no == 1
    assert [answer.revision for answer in current.answer_history] == [1, 2]


@pytest.mark.asyncio
async def test_two_concurrent_votes_cross_threshold_once() -> None:
    service, repository, clock = setup()
    poll = await service.open(
        synthetic_id("case-three"),
        floor_audience(),
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="open-case-three",
    )
    poll_id = poll.definition.poll_id
    for number in (1, 2):
        await service.record_answer(
            poll_id,
            VoteChoice.YES,
            synthetic_id(f"initial-vote-{number}"),
            clock.now(),
            context(number),
        )

    results = await asyncio.gather(
        service.record_answer(
            poll_id,
            VoteChoice.YES,
            synthetic_id("cross-three"),
            clock.now(),
            context(3),
        ),
        service.record_answer(
            poll_id, VoteChoice.YES, synthetic_id("cross-four"), clock.now(), context(4)
        ),
    )

    current = repository.by_id[poll_id]
    assert current.tally.yes == 3
    assert current.status == PollStatus.CLOSED
    assert current.outcome == ProblemOutcome.REQUEST_READY
    assert repository.events.count("poll.threshold_reached") == 1
    assert sum(bool(result.events) for result in results) == 1


@pytest.mark.asyncio
async def test_wrong_house_actor_and_late_answer_do_not_mutate_poll() -> None:
    service, repository, clock = setup()
    poll = await service.open(
        synthetic_id("case-four"),
        floor_audience(),
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="open-case-four",
    )
    poll_id = poll.definition.poll_id

    with pytest.raises(ValueError, match="another house"):
        await service.record_answer(
            poll_id,
            VoteChoice.YES,
            synthetic_id("wrong-house"),
            clock.now(),
            context(1, house_id=HOUSE_TWO),
        )
    outsider = await service.record_answer(
        poll_id, VoteChoice.YES, synthetic_id("outsider"), clock.now(), context(19)
    )
    late = await service.record_answer(
        poll_id,
        VoteChoice.YES,
        synthetic_id("late"),
        poll.definition.closes_at,
        context(1),
    )

    assert outsider.answer_result is not None
    assert outsider.answer_result.status == AnswerStatus.NOT_ELIGIBLE
    assert late.answer_result is not None
    assert late.answer_result.status == AnswerStatus.LATE
    assert repository.by_id[poll_id].version == 1


@pytest.mark.asyncio
async def test_ingress_before_deadline_counts_even_if_worker_is_late() -> None:
    service, repository, clock = setup()
    poll = await service.open(
        synthetic_id("case-five"),
        floor_audience(),
        PollKind.PROBLEM_CONFIRMATION,
        demo_problem_policy(),
        1,
        context(1),
        operation_key="open-case-five",
    )
    clock.current = poll.definition.closes_at + timedelta(minutes=1)

    answer = await service.record_answer(
        poll.definition.poll_id,
        VoteChoice.YES,
        synthetic_id("on-time-ingress"),
        poll.definition.closes_at - timedelta(microseconds=1),
        context(1),
    )
    finalized = await service.finalize(poll.definition.poll_id, context(1))

    assert answer.answer_result is not None
    assert answer.answer_result.status == AnswerStatus.RECORDED
    assert finalized.state.outcome == ProblemOutcome.NEED_EVIDENCE
    assert repository.events == ["poll.finalized"]


@pytest.mark.asyncio
async def test_initiative_and_resolution_finalize_from_frozen_policy() -> None:
    service, repository, clock = setup()
    audience = floor_audience()
    initiative = await service.open(
        synthetic_id("initiative-two"),
        audience,
        PollKind.INITIATIVE_POSITION,
        demo_initiative_policy(),
        2,
        context(1),
        operation_key="initiative-two",
        window=timedelta(hours=1),
    )
    resolution = await service.open(
        synthetic_id("case-six"),
        audience,
        PollKind.RESOLUTION_CHECK,
        demo_resolution_policy(),
        1,
        context(1),
        operation_key="resolution-six",
        window=timedelta(hours=1),
    )
    for number in range(1, 7):
        await service.record_answer(
            initiative.definition.poll_id,
            VoteChoice.YES if number <= 4 else VoteChoice.NO,
            synthetic_id(f"initiative-event-{number}"),
            clock.now(),
            context(number),
        )
        await service.record_answer(
            resolution.definition.poll_id,
            VoteChoice.YES if number <= 4 else VoteChoice.NO,
            synthetic_id(f"resolution-event-{number}"),
            clock.now(),
            context(number),
        )
    clock.current += timedelta(hours=1)

    initiative_result = await service.finalize(
        initiative.definition.poll_id, context(1)
    )
    resolution_result = await service.finalize(
        resolution.definition.poll_id, context(1)
    )

    assert initiative_result.state.outcome == InitiativeOutcome.SUPPORTED
    assert resolution_result.state.outcome == ResolutionOutcome.REOPENED
    assert repository.events.count("poll.finalized") == 2


@pytest.mark.asyncio
async def test_open_rejects_other_house_empty_audience_and_wrong_window() -> None:
    service, repository, _ = setup()
    audience = floor_audience()

    with pytest.raises(ValueError, match="another house"):
        await service.open(
            synthetic_id("case-seven"),
            audience,
            PollKind.PROBLEM_CONFIRMATION,
            demo_problem_policy(),
            1,
            context(1, house_id=HOUSE_TWO),
            operation_key="wrong-house",
        )
    empty = AudienceSnapshot(
        audience_id=synthetic_id("empty-audience"),
        house_id=HOUSE_ONE,
        scope=AudienceScope(kind=ScopeKind.HOUSE),
        criteria_revision=1,
        members=(),
        created_at=audience.created_at,
    )
    with pytest.raises(ValueError, match="without an eligible"):
        await service.open(
            synthetic_id("case-eight"),
            empty,
            PollKind.PROBLEM_CONFIRMATION,
            demo_problem_policy(),
            1,
            context(1),
            operation_key="empty",
        )
    with pytest.raises(ValueError, match="trusted window"):
        await service.open(
            synthetic_id("initiative-three"),
            audience,
            PollKind.INITIATIVE_POSITION,
            demo_initiative_policy(),
            1,
            context(1),
            operation_key="missing-window",
        )
    assert not repository.by_id
