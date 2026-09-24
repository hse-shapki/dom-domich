from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from dom_domych.domain.polls.policy import (
    InitiativeOutcome,
    ProblemOutcome,
    ResolutionOutcome,
    VoteTally,
    demo_initiative_policy,
    demo_problem_policy,
    demo_resolution_policy,
    evaluate_initiative,
    evaluate_problem,
    evaluate_resolution,
    initiative_progress,
    received_during_poll,
)


@pytest.mark.parametrize(
    ("eligible", "yes", "expired", "expected"),
    [
        (12, 2, False, ProblemOutcome.COLLECTING),
        (12, 2, True, ProblemOutcome.NEED_EVIDENCE),
        (12, 3, False, ProblemOutcome.REQUEST_READY),
        (12, 3, True, ProblemOutcome.REQUEST_READY),
        (1, 1, False, ProblemOutcome.REQUEST_READY),
        (0, 0, True, ProblemOutcome.NO_AUDIENCE),
    ],
)
def test_problem_threshold_and_expiry(
    eligible: int, yes: int, expired: bool, expected: ProblemOutcome
) -> None:
    tally = VoteTally(eligible=eligible, yes=yes, no=0)

    result = evaluate_problem(tally, demo_problem_policy(), expired=expired)

    assert result == expected


def test_problem_policy_keeps_five_hour_demo_window() -> None:
    policy = demo_problem_policy()

    assert policy.wait_period == timedelta(hours=5)
    assert policy.threshold_ratio == Decimal("0.20")
    assert policy.demo is True


def test_initiative_tracks_three_distinct_ratios() -> None:
    tally = VoteTally(eligible=10, yes=4, no=2)

    progress = initiative_progress(tally)

    assert progress.participation == Decimal("0.6")
    assert progress.support_total == Decimal("0.4")
    assert progress.support_answered == Decimal(4) / Decimal(6)
    assert (
        evaluate_initiative(tally, demo_initiative_policy(), finalized=True)
        == InitiativeOutcome.SUPPORTED
    )


@pytest.mark.parametrize(
    ("tally", "finalized", "expected"),
    [
        (VoteTally(eligible=0, yes=0, no=0), True, InitiativeOutcome.NO_AUDIENCE),
        (VoteTally(eligible=10, yes=4, no=2), False, InitiativeOutcome.COLLECTING),
        (VoteTally(eligible=10, yes=2, no=2), True, InitiativeOutcome.NOT_SUPPORTED),
        (VoteTally(eligible=10, yes=2, no=4), True, InitiativeOutcome.NOT_SUPPORTED),
        (VoteTally(eligible=10, yes=3, no=2), True, InitiativeOutcome.SUPPORTED),
    ],
)
def test_initiative_final_result(
    tally: VoteTally, finalized: bool, expected: InitiativeOutcome
) -> None:
    assert (
        evaluate_initiative(tally, demo_initiative_policy(), finalized=finalized)
        == expected
    )


def test_initiative_empty_ratios_are_not_fake_zero_votes() -> None:
    progress = initiative_progress(VoteTally(eligible=0, yes=0, no=0))

    assert progress.participation is None
    assert progress.support_total is None
    assert progress.support_answered is None


@pytest.mark.parametrize(
    ("tally", "finalized", "expected"),
    [
        (VoteTally(eligible=10, yes=4, no=1), True, ResolutionOutcome.CLOSED),
        (VoteTally(eligible=10, yes=3, no=2), True, ResolutionOutcome.REOPENED),
        (VoteTally(eligible=10, yes=1, no=0), True, ResolutionOutcome.UNCONFIRMED),
        (VoteTally(eligible=10, yes=0, no=1), True, ResolutionOutcome.REOPENED),
        (VoteTally(eligible=10, yes=10, no=0), False, ResolutionOutcome.CHECKING),
        (VoteTally(eligible=0, yes=0, no=0), True, ResolutionOutcome.UNCONFIRMED),
    ],
)
def test_resolution_requires_resident_result(
    tally: VoteTally, finalized: bool, expected: ResolutionOutcome
) -> None:
    assert (
        evaluate_resolution(tally, demo_resolution_policy(), finalized=finalized)
        == expected
    )


def test_vote_tally_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError, match="invalid vote tally"):
        VoteTally(eligible=2, yes=2, no=1)


def test_poll_accepts_ingress_before_deadline_only() -> None:
    start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    end = start + timedelta(hours=5)

    assert received_during_poll(start, start, end)
    assert received_during_poll(end - timedelta(microseconds=1), start, end)
    assert not received_during_poll(end, start, end)
    assert not received_during_poll(start - timedelta(seconds=1), start, end)


def test_poll_rejects_naive_or_reversed_timestamps() -> None:
    start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="timezone-aware"):
        received_during_poll(
            start.replace(tzinfo=None), start, start + timedelta(hours=1)
        )
    with pytest.raises(ValueError, match="later"):
        received_during_poll(start, start, start)
