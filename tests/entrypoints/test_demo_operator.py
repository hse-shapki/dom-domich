"""A06: operator CLI выполняет доверенные команды без ручного SQL."""

import hashlib
import os

import pytest
from sqlalchemy import delete, select, update

from dom_domych.entrypoints.demo_operator import build_parser, run_command
from dom_domych.infrastructure.postgres.models import (
    DemoInvitationRow,
    HouseRow,
    ResidencyRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("demo operator CLI requires dedicated migrated PostgreSQL test database")
    return value


def test_demo_operator_requires_explicit_adult_verification() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "issue-invitation",
                "--house-id",
                str(HOUSE_ONE),
                "--residency-id",
                str(synthetic_id("residency-missing")),
            ]
        )


@pytest.mark.asyncio
async def test_demo_operator_issues_digest_only_invitation_and_binds_house_chat() -> None:
    database_url = database_url_for_test()
    resident_id = synthetic_id("resident-13")
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            residency_id = await session.scalar(
                select(ResidencyRow.id).where(
                    ResidencyRow.resident_id == resident_id,
                    ResidencyRow.house_id == HOUSE_ONE,
                )
            )
            assert residency_id is not None

    parser = build_parser()
    token = await run_command(
        parser.parse_args(
            [
                "issue-invitation",
                "--house-id",
                str(HOUSE_ONE),
                "--residency-id",
                str(residency_id),
                "--adult-verified",
                "--ttl-hours",
                "1",
            ]
        ),
        database_url,
    )
    result = await run_command(
        parser.parse_args(
            [
                "bind-house-chat",
                "--house-id",
                str(HOUSE_ONE),
                "--max-chat-id",
                "100500",
            ]
        ),
        database_url,
    )
    assert result == "ok"

    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            invitation = await session.scalar(
                select(DemoInvitationRow).where(
                    DemoInvitationRow.residency_id == residency_id,
                    DemoInvitationRow.token_digest == hashlib.sha256(token.encode()).hexdigest(),
                )
            )
            assert invitation is not None
            assert token not in invitation.token_digest
            assert (
                await session.scalar(select(HouseRow.max_chat_id).where(HouseRow.id == HOUSE_ONE))
                == "100500"
            )
            await session.execute(
                delete(DemoInvitationRow).where(DemoInvitationRow.residency_id == residency_id)
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=None)
            )
