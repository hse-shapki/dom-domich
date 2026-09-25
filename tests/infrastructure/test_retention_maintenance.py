import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from dom_domych.application.jobs.maintenance import RetentionMaintenance
from dom_domych.infrastructure.files.local import FileKind, LocalFileStore, StoredFileNotFound
from dom_domych.infrastructure.postgres.models import InboxEventRow, OutboxDeliveryRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


def database_url_for_test() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "")
    if "dom_domych_test" not in value:
        pytest.skip("retention test requires dedicated migrated PostgreSQL")
    return value


@pytest.mark.asyncio
async def test_maintenance_redacts_terminal_payloads_and_purges_expired_files(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    old = clock.now() - timedelta(days=60)
    inbox_id = uuid4()
    ignored_id = uuid4()
    delivery_id = uuid4()
    files = LocalFileStore(tmp_path, clock)
    stored = await files.put(
        HOUSE_ONE,
        FileKind.DOCUMENT,
        "application/pdf",
        b"%PDF-1.4\nsynthetic",
        retain_until=clock.now() + timedelta(days=1),
    )

    async with database_lifespan(database_url_for_test()) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            session.add(
                InboxEventRow(
                    id=inbox_id,
                    source="max",
                    source_key=f"retention:{inbox_id}",
                    event_name="message.received",
                    raw_update={"message": {"body": {"text": "частное сообщение"}}},
                    normalized_event={"message": {"text": "частное сообщение"}},
                    received_at=old,
                    available_at=old,
                    status="done",
                )
            )
            session.add(
                InboxEventRow(
                    id=ignored_id,
                    source="max",
                    source_key=f"retention:{ignored_id}",
                    raw_update={"update_type": "future_private_event"},
                    normalized_event=None,
                    received_at=old,
                    available_at=old,
                    status="ignored",
                )
            )
            session.add(
                OutboxDeliveryRow(
                    id=delivery_id,
                    house_id=HOUSE_ONE,
                    operation_key=f"retention:{delivery_id}",
                    text="Персональный ответ",
                    chat_id="123",
                    status="sent",
                    attempts=1,
                    available_at=old,
                )
            )
        clock.current += timedelta(days=2)
        redacted, deleted = await RetentionMaintenance(
            sessions, files, clock, timedelta(days=30)
        ).run_once()
        assert redacted.inbox_events == 2
        assert redacted.outbox_deliveries == 1
        assert deleted == 1
        async with sessions.begin() as session:
            inbox = await session.get(InboxEventRow, inbox_id)
            ignored = await session.get(InboxEventRow, ignored_id)
            delivery = await session.get(OutboxDeliveryRow, delivery_id)
            assert inbox is not None and inbox.normalized_event is None
            assert inbox.raw_update == {"redacted": True, "reason": "retention_expired"}
            assert ignored is not None and ignored.raw_update == {
                "redacted": True,
                "reason": "retention_expired",
            }
            assert delivery is not None and delivery.text == "[удалено по сроку хранения]"
            await session.execute(
                delete(InboxEventRow).where(InboxEventRow.id.in_((inbox_id, ignored_id)))
            )
            await session.execute(
                delete(OutboxDeliveryRow).where(OutboxDeliveryRow.id == delivery_id)
            )
    with pytest.raises(StoredFileNotFound):
        await files.get(HOUSE_ONE, stored.file_key)
