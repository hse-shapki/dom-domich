"""A06: demo-код подтверждает квартиру и привязывает MAX actor в личке."""

import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete, select, update

from dom_domych.application.residents.enrollment import (
    DemoEnrollmentService,
    EnrollmentDenied,
    TrustedDemoOperator,
)
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.max.onboarding import MaxOnboardingHandler
from dom_domych.infrastructure.max.updates import normalize_update
from dom_domych.infrastructure.postgres.enrollment import PostgresEnrollment
from dom_domych.infrastructure.postgres.models import (
    DemoInvitationRow,
    ResidencyRow,
    ResidentRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("A06 requires dedicated migrated PostgreSQL test database")
    return value


@pytest.mark.asyncio
async def test_demo_invitation_onboards_from_max_dm_and_marks_stopped_chat_unreachable() -> None:
    clock = FixedClock()
    resident_id = synthetic_id("resident-13")
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"body": {"mid": "onboard.1"}}})

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            residency = await session.scalar(
                select(ResidencyRow).where(
                    ResidencyRow.resident_id == resident_id,
                    ResidencyRow.house_id == HOUSE_ONE,
                )
            )
            assert residency is not None and not residency.confirmed
            service = DemoEnrollmentService(PostgresEnrollment(session), clock)
            with pytest.raises(EnrollmentDenied):
                await service.issue_invitation(
                    residency.id,
                    TrustedDemoOperator(HOUSE_ONE, frozenset()),
                    adult_verified=True,
                )
            code = await service.issue_invitation(
                residency.id,
                TrustedDemoOperator(HOUSE_ONE, frozenset({"demo.residency_confirm"})),
                adult_verified=True,
            )
        raw_message: dict[str, object] = {
            "update_type": "message_created",
            "timestamp": int(clock.now().timestamp() * 1000),
            "message": {
                "sender": {"user_id": 313},
                "recipient": {"user_id": 900},
                "timestamp": int(clock.now().timestamp() * 1000),
                "body": {"mid": "start.1", "text": f"/start {code}"},
            },
        }
        _, event = normalize_update(raw_message, clock.now())
        assert event is not None
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
        ) as http:
            handler = MaxOnboardingHandler(sessions, MaxApiClient(http, "test-token"), clock)
            assert await handler.handle(event)
            stopped_raw: dict[str, object] = {
                "update_type": "bot_stopped",
                "timestamp": int(clock.now().timestamp() * 1000),
                "user": {"user_id": 313},
            }
            _, stopped = normalize_update(stopped_raw, clock.now())
            assert stopped is not None and await handler.handle(stopped)
        async with sessions.begin() as session:
            resident = await session.get(ResidentRow, resident_id)
            residency = await session.scalar(
                select(ResidencyRow).where(
                    ResidencyRow.resident_id == resident_id,
                    ResidencyRow.house_id == HOUSE_ONE,
                )
            )
            assert resident is not None and resident.max_user_id == "313"
            assert resident.active_house_id == HOUSE_ONE and not resident.dm_reachable
            assert residency is not None and residency.confirmed and residency.adult
            await session.execute(
                delete(DemoInvitationRow).where(DemoInvitationRow.residency_id == residency.id)
            )
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id == resident_id)
                .values(max_user_id=None, active_house_id=None, dm_reachable=True)
            )
            await session.execute(
                update(ResidencyRow)
                .where(ResidencyRow.id == residency.id)
                .values(confirmed=False, source="demo")
            )
    assert len(seen) == 1 and seen[0].url.params["user_id"] == "313"
