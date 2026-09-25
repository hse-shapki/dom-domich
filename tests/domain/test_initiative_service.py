import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from dom_domych.application.initiatives.service import InitiativeService
from dom_domych.domain.initiatives.models import (
    InitiativeConflict,
    InitiativeForbidden,
    InitiativeState,
)
from dom_domych.domain.polls.models import AnswerStatus, PollStatus, VoteChoice
from dom_domych.domain.polls.policy import demo_initiative_policy
from tests.domain.test_poll_service import floor_audience
from tests.fakes.initiatives import FakeCase, FakeCasePort, FakeInitiativeRepository
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, synthetic_id

AUTHOR = synthetic_id("resident-1")
CASE_ID = synthetic_id("initiative-case")


@dataclass(frozen=True)
class Context:
    house_id: UUID
    actor_id: UUID


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


def setup() -> tuple[InitiativeService, FakeInitiativeRepository]:
    repository = FakeInitiativeRepository()
    cases = FakeCasePort(FakeCase(CASE_ID, HOUSE_ONE, AUTHOR))
    return InitiativeService(cases, repository, FakeClock()), repository


async def create(service: InitiativeService, operation_key: str = "create-v1") -> InitiativeState:
    return await service.create(
        CASE_ID,
        "  Поставить велопарковку у второго подъезда  ",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        operation_key=operation_key,
    )


@pytest.mark.asyncio
async def test_create_uses_existing_case_and_opens_poll_for_frozen_audience() -> None:
    service, repository = setup()

    state = await create(service)
    poll = repository.polls[state.current.poll_id]

    assert state.case_id == CASE_ID
    assert state.current.wording == "Поставить велопарковку у второго подъезда"
    assert state.current.revision == 1
    assert poll.definition.subject_revision == 1
    assert poll.tally.eligible == 12
    assert len(repository.notifications[poll.definition.poll_id]) == 12
    assert repository.events == [("initiative.created", CASE_ID)]


@pytest.mark.asyncio
async def test_change_wording_cancels_old_poll_and_starts_zero_votes() -> None:
    service, repository = setup()
    original = await create(service)
    old_id = original.current.poll_id
    answer = repository.polls[old_id].record_answer(
        AUTHOR,
        VoteChoice.YES,
        synthetic_id("first-vote"),
        FakeClock().now() + timedelta(minutes=1),
    )
    repository.polls[old_id] = answer.state

    revised = await service.revise(
        CASE_ID,
        "Велопарковка на шесть мест у подъезда 2",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        expected_revision=1,
        operation_key="revise-v2",
    )
    new_poll = repository.polls[revised.current.poll_id]
    late_button = repository.polls[old_id].record_answer(
        synthetic_id("resident-2"),
        VoteChoice.YES,
        synthetic_id("stale-button"),
        FakeClock().now() + timedelta(minutes=2),
    )

    assert len(revised.revisions) == 2
    assert original.current.wording == revised.revisions[0].wording
    assert repository.polls[old_id].status is PollStatus.CANCELLED
    assert old_id in repository.revoked_poll_ids
    assert repository.polls[old_id].tally.yes == 1
    assert new_poll.tally.yes == 0
    assert late_button.answer_result is not None
    assert late_button.answer_result.status is AnswerStatus.CLOSED
    assert repository.events == [
        ("initiative.created", CASE_ID),
        ("initiative.revised", CASE_ID),
    ]


@pytest.mark.asyncio
async def test_repeated_create_and_revise_key_do_not_duplicate_polls() -> None:
    service, repository = setup()
    original, repeated = await asyncio.gather(create(service), create(service))

    first = await service.revise(
        CASE_ID,
        "Велопарковка на шесть мест",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        expected_revision=1,
        operation_key="revise-v2",
    )
    second = await service.revise(
        CASE_ID,
        "Велопарковка на шесть мест",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        expected_revision=1,
        operation_key="revise-v2",
    )

    assert original == repeated
    assert first == second
    assert len(repository.polls) == 2


@pytest.mark.asyncio
async def test_author_house_and_revision_are_checked() -> None:
    service, repository = setup()
    await create(service)

    with pytest.raises(InitiativeForbidden):
        await service.revise(
            CASE_ID,
            "Чужая редакция",
            floor_audience(),
            demo_initiative_policy(),
            timedelta(days=2),
            Context(HOUSE_ONE, synthetic_id("resident-2")),
            expected_revision=1,
            operation_key="forged-author",
        )
    with pytest.raises(ValueError, match="case not found"):
        await service.create(
            CASE_ID,
            "Чужой дом",
            floor_audience(),
            demo_initiative_policy(),
            timedelta(days=2),
            Context(HOUSE_TWO, AUTHOR),
            operation_key="forged-house",
        )
    with pytest.raises(InitiativeConflict, match="revision changed"):
        await service.revise(
            CASE_ID,
            "Старая версия",
            floor_audience(),
            demo_initiative_policy(),
            timedelta(days=2),
            Context(HOUSE_ONE, AUTHOR),
            expected_revision=0,
            operation_key="stale-revision",
        )
    assert len(repository.polls) == 1


@pytest.mark.asyncio
async def test_operation_key_cannot_be_reused_for_different_wording() -> None:
    service, repository = setup()
    await create(service)

    with pytest.raises(InitiativeConflict, match="operation key"):
        await service.create(
            CASE_ID,
            "Совсем иная формулировка",
            floor_audience(),
            demo_initiative_policy(),
            timedelta(days=2),
            Context(HOUSE_ONE, AUTHOR),
            operation_key="create-v1",
        )
    assert len(repository.polls) == 1


@pytest.mark.asyncio
async def test_concurrent_edits_of_same_revision_leave_one_active_poll() -> None:
    service, repository = setup()
    original = await create(service)

    async def revise(wording: str, key: str) -> InitiativeState:
        return await service.revise(
            CASE_ID,
            wording,
            floor_audience(),
            demo_initiative_policy(),
            timedelta(days=2),
            Context(HOUSE_ONE, AUTHOR),
            expected_revision=1,
            operation_key=key,
        )

    results = await asyncio.gather(
        revise("Велопарковка на 6 мест", "edit-a"),
        revise("Велопарковка на 8 мест", "edit-b"),
        return_exceptions=True,
    )

    assert len([result for result in results if isinstance(result, InitiativeConflict)]) == 1
    assert len(repository.polls) == 2
    assert repository.polls[original.current.poll_id].status is PollStatus.CANCELLED
    assert sum(poll.status is PollStatus.OPEN for poll in repository.polls.values()) == 1
