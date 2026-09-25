from dataclasses import replace
from datetime import timedelta

import pytest

from dom_domych.application.cards.builders import (
    ProgressScale,
    initiative_card,
    problem_card,
    status_card,
)
from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.domain.executor.models import ExternalStatus
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.polls.policy import demo_initiative_policy, demo_problem_policy
from tests.domain.test_demo_executor import REGISTER, SUBMIT, draft
from tests.domain.test_demo_executor import FakeClock as ExecutorClock
from tests.domain.test_initiative_service import (
    AUTHOR,
    CASE_ID,
    Context,
)
from tests.domain.test_initiative_service import (
    setup as setup_initiative,
)
from tests.domain.test_poll_service import context, floor_audience
from tests.domain.test_poll_service import setup as setup_poll
from tests.fakes.executor import FakeExecutorStore
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


def test_progress_scale_handles_zero_denominator_and_exact_percent() -> None:
    assert ProgressScale.build("Участие", 0, 0).line() == "Участие: 0/0 (—) ░░░░░░░░░░"
    assert ProgressScale.build("Участие", 7, 12).percentage == "58,3%"
    with pytest.raises(ValueError):
        ProgressScale.build("Неверно", 13, 12)


@pytest.mark.asyncio
async def test_initiative_card_separates_participation_and_support() -> None:
    service, repository = setup_initiative()
    state = await service.create(
        CASE_ID,
        "Поставить велопарковку у второго подъезда",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        operation_key="card-open",
    )
    poll = repository.polls[state.current.poll_id]
    for number, choice in (
        (1, VoteChoice.YES),
        (2, VoteChoice.YES),
        (3, VoteChoice.NO),
    ):
        mutation = poll.record_answer(
            synthetic_id(f"resident-{number}"),
            choice,
            synthetic_id(f"card-answer-{number}"),
            poll.definition.opens_at + timedelta(minutes=1),
        )
        poll = mutation.state

    card = initiative_card(state, poll)

    assert "Участие: 3/12 (25,0%)" in card.text
    assert "За от всех: 2/12 (16,7%)" in card.text
    assert "За среди ответивших: 2/3 (66,7%)" in card.text
    assert "не протокол ОСС" in card.text
    assert all(str(answer.resident_id) not in card.text for answer in poll.answers)
    assert card.edit_key == f"initiative:{CASE_ID}"
    assert card.source_version == f"1:{poll.version}"


@pytest.mark.asyncio
async def test_card_rejects_poll_of_previous_initiative_revision() -> None:
    service, repository = setup_initiative()
    state = await service.create(
        CASE_ID,
        "Велопарковка",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        operation_key="old-card",
    )
    old_poll = repository.polls[state.current.poll_id]
    revised = await service.revise(
        CASE_ID,
        "Велопарковка на шесть мест",
        floor_audience(),
        demo_initiative_policy(),
        timedelta(days=2),
        Context(HOUSE_ONE, AUTHOR),
        expected_revision=1,
        operation_key="new-card",
    )

    with pytest.raises(ValueError, match="does not match"):
        initiative_card(revised, old_poll)


@pytest.mark.asyncio
async def test_problem_card_uses_frozen_denominator_not_reachable_count() -> None:
    service, _, _ = setup_poll()
    poll = await service.open(
        synthetic_id("light-case"),
        floor_audience(),
        kind=PollKind.PROBLEM_CONFIRMATION,
        policy=demo_problem_policy(),
        subject_revision=1,
        context=context(1),
        operation_key="problem-card",
    )

    card = problem_card("Не горит свет", poll)

    assert "Подтвердили: 0/12" in card.text
    assert "Недоставка ЛС не меняет это число" in card.text
    assert card.demo is True


@pytest.mark.asyncio
async def test_done_status_card_does_not_claim_resident_confirmation() -> None:
    service = DemoExecutorService(FakeExecutorStore(), ExecutorClock())
    operation = await service.submit(draft(), "status-card", SUBMIT)
    registered, _ = await service.register(operation.operation_id, REGISTER)
    done = replace(registered, status=ExternalStatus.DONE)

    card = status_card("Не горит свет", done, "checking_resolution", CASE_ID)

    assert "Исполнитель сообщил о выполнении" in card.text
    assert "жители проверяют результат" in card.text
    assert "закрыто" not in card.text
    assert "ДЕМО" in card.text
