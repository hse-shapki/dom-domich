import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from dom_domych.domain.ports.core import DeliveryIntent
from dom_domych.entrypoints.diagnostics import snapshot
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import OutboxDeliveryRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("runtime diagnostics require a dedicated migrated PostgreSQL test database")
    return value


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 30, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_snapshot_is_redacted_read_only_and_reports_delivery_unknown() -> None:
    database_url = database_url_for_test()
    clock = FixedClock()
    operation_key = f"diagnostics:{uuid4()}"
    recipient_id = synthetic_id("resident-2")
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            delivery_id = await PostgresDeliveryQueue(session, clock).enqueue(
                DeliveryIntent(
                    HOUSE_ONE,
                    operation_key,
                    "private diagnostic payload",
                    recipient_id=recipient_id,
                )
            )
            await session.execute(
                update(OutboxDeliveryRow)
                .where(OutboxDeliveryRow.id == delivery_id)
                .values(status="delivery_unknown", error_code="transport_uncertain")
            )

        result = await snapshot(database_url, clock.now())

        assert "outbox.delivery_unknown" in result.alerts
        assert result.outbox.statuses["delivery_unknown"] >= 1
        assert operation_key not in repr(result)
        assert "private diagnostic payload" not in repr(result)
        async with sessions.begin() as session:
            persisted = await session.scalar(
                select(OutboxDeliveryRow).where(OutboxDeliveryRow.id == delivery_id)
            )
            assert persisted is not None and persisted.status == "delivery_unknown"
            await session.execute(
                delete(OutboxDeliveryRow).where(OutboxDeliveryRow.id == delivery_id)
            )


@pytest.mark.asyncio
async def test_snapshot_rejects_unsupported_table_without_sql_interpolation() -> None:
    database_url = database_url_for_test()
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            from dom_domych.entrypoints.diagnostics import _queue_health

            with pytest.raises(ValueError, match="unsupported diagnostic table"):
                await _queue_health(
                    session,
                    "outbox_deliveries; DROP TABLE houses",
                    ready_column="available_at",
                    now=FixedClock().now(),
                )
