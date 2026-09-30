import asyncio
from dataclasses import asdict

from dom_domych.demo.house import demo_residencies
from scripts.seed_demo_house import _demo_seed_allowed
from tests.fixtures.zamira_house import (
    HOUSE_ONE,
    HOUSE_TWO,
    RISER_E2_A,
    FakeResidentDirectory,
    synthetic_id,
    zamira_fixture,
)


def test_runtime_demo_seed_matches_fixture_registry() -> None:
    fixture_rows = zamira_fixture().residencies
    runtime_rows = demo_residencies()

    assert tuple(asdict(row) for row in runtime_rows) == tuple(asdict(row) for row in fixture_rows)


def test_demo_seed_needs_test_database_or_explicit_demo_database() -> None:
    assert _demo_seed_allowed("postgresql+asyncpg://u@db/dom_domych_test", explicit_demo=False)
    assert _demo_seed_allowed("postgresql+asyncpg://u@db/dom_domych_demo", explicit_demo=True)
    assert not _demo_seed_allowed("postgresql+asyncpg://u@db/dom_domych", explicit_demo=True)
    assert not _demo_seed_allowed("postgresql+asyncpg://u@db/dom_domych_demo", explicit_demo=False)


def test_fixture_has_twelve_distinct_reporters_and_a_repeat() -> None:
    fixture = zamira_fixture()

    assert len(fixture.same_problem_messages) == 12
    assert len({item.author_id for item in fixture.same_problem_messages}) == 12
    assert len(fixture.repeated_messages) == 12
    assert {item.author_id for item in fixture.repeated_messages} == {
        fixture.same_problem_messages[0].author_id
    }
    assert fixture.different_problem_message.author_id not in {
        item.author_id for item in fixture.same_problem_messages
    }


def test_fixture_exposes_reachability_and_eligibility_separately() -> None:
    fixture = zamira_fixture()
    floor = [
        item
        for item in fixture.residencies
        if item.house_id == HOUSE_ONE
        and item.entrance == 2
        and item.floor == 5
        and item.confirmed
        and item.adult
        and item.active
    ]

    assert len(floor) == 12
    assert len({item.resident_id for item in floor}) == 12
    assert sum(item.dm_reachable for item in floor) == 11
    assert sum(RISER_E2_A in item.riser_ids for item in floor) == 6
    assert any(item.confirmed is False for item in fixture.residencies)
    assert any(item.adult is False for item in fixture.residencies)


def test_fake_directory_is_house_scoped_and_keeps_overlapping_residencies() -> None:
    directory = FakeResidentDirectory(zamira_fixture())

    house_one = asyncio.run(directory.list_house_residencies(HOUSE_ONE))
    house_two = asyncio.run(directory.list_house_residencies(HOUSE_TWO))

    assert house_one and all(item.house_id == HOUSE_ONE for item in house_one)
    assert len(house_two) == 1
    assert house_two[0].resident_id == synthetic_id("resident-19")
    assert sum(item.resident_id == synthetic_id("resident-1") for item in house_one) == 2


def test_fixture_contains_late_vote_revision_and_negative_result() -> None:
    fixture = zamira_fixture()

    assert fixture.late_answer_at > fixture.closes_at
    assert fixture.changed_initiative_text.endswith("навес")
    assert len(fixture.negative_resolution_residents) == 2
