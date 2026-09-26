"""K14: MAX inbox → trusted triage → production case tool → reply outbox."""

import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from dom_domych.agent.llm import FakeLlmPort, LlmResponse, LlmToolCall
from dom_domych.application.agent.composition import (
    build_k_coordinator,
    build_k_message_agent,
)
from dom_domych.application.agent.messages import register_message_agent
from dom_domych.application.jobs.inbox_worker import EventDispatcher, InboxWorker
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource, MessagePayload
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation
from dom_domych.infrastructure.postgres.agent_models import AgentRunRow
from dom_domych.infrastructure.postgres.case_models import (
    CaseEventRow,
    CaseMessageRow,
    CaseOperationRow,
    CaseRow,
)
from dom_domych.infrastructure.postgres.inbox import save_inbox_event
from dom_domych.infrastructure.postgres.models import (
    ApartmentRow,
    HouseRow,
    InboxEventRow,
    OutboxDeliveryRow,
    ResidencyRow,
    ResidentRow,
)
from dom_domych.infrastructure.postgres.session import database_lifespan

NOW = datetime(2026, 9, 26, 16, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class UnusedSubmitter:
    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation:
        raise AssertionError("triage must not submit an unapproved request")


@pytest.mark.asyncio
async def test_message_creates_one_scoped_case_and_queues_reply() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, apartment_id, resident_id, residency_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    event_id, operation_id = uuid4(), uuid4()
    event = EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"message_created:777:{event_id}",
        name=EventName.MESSAGE_RECEIVED,
        occurred_at=NOW,
        received_at=NOW,
        correlation_id=event_id,
        actor_user_id="42",
        message=MessagePayload(
            chat_id="777",
            message_id="max-message-1",
            sender_user_id="42",
            text="В первом подъезде не горит свет",
        ),
    )
    create_arguments = json.dumps(
        {
            "kind": "problem",
            "title": "Не горит свет",
            "description": "В первом подъезде не горит свет",
            "entrance": 1,
            "floor": None,
            "object_name": "lighting",
            "source_message_id": str(event_id),
            "candidate_case_ids": [],
            "operation_id": str(operation_id),
        }
    )
    llm = FakeLlmPort(
        [
            LlmResponse(
                '{"items":[{"kind":"problem","text":"Не горит свет",'
                '"entrance":1,"object_name":"lighting"}]}'
            ),
            LlmResponse("", (LlmToolCall("case.create", create_arguments),)),
            LlmResponse("Создала дело о неработающем освещении."),
        ]
    )
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add(
                HouseRow(
                    id=house_id,
                    address="K14 дом сообщений",
                    timezone="UTC",
                    max_chat_id="777",
                    demo=True,
                )
            )
            await session.flush()
            session.add_all(
                [
                    ApartmentRow(
                        id=apartment_id,
                        house_id=house_id,
                        number="1",
                        entrance=1,
                        floor=1,
                    ),
                    ResidentRow(
                        id=resident_id,
                        max_user_id="42",
                        display_name="Житель K14",
                        dm_reachable=True,
                        active_house_id=house_id,
                    ),
                ]
            )
            await session.flush()
            session.add(
                ResidencyRow(
                    id=residency_id,
                    house_id=house_id,
                    apartment_id=apartment_id,
                    resident_id=resident_id,
                    confirmed=True,
                    adult=True,
                    valid_from=NOW,
                    valid_until=None,
                    source="synthetic",
                )
            )
            assert await save_inbox_event(session, event.source_key, event, {}, NOW)
        try:
            clock = FixedClock()
            coordinator = build_k_coordinator(sessions, llm, clock, UnusedSubmitter())
            handler = build_k_message_agent(
                sessions,
                llm,
                clock,
                coordinator,
                frozenset({"case.read", "case.write", "knowledge.read"}),
            )
            dispatcher = EventDispatcher({})
            register_message_agent(dispatcher, handler)
            worker = InboxWorker(sessions, dispatcher, clock, "k14-message-worker")

            assert await worker.run_once()
            assert not await worker.run_once()
            assert llm.call_count == 3

            async with sessions() as session:
                case = await session.scalar(select(CaseRow).where(CaseRow.house_id == house_id))
                assert case is not None
                assert case.kind == "problem" and case.status == "detected"
                origin = await session.get(CaseMessageRow, (case.id, event_id))
                assert origin is not None and origin.actor_id == resident_id
                run = await session.scalar(
                    select(AgentRunRow).where(AgentRunRow.event_id == event_id)
                )
                assert run is not None and run.status == "completed"
                delivery = await session.scalar(
                    select(OutboxDeliveryRow).where(
                        OutboxDeliveryRow.operation_key == f"agent-reply:{event_id}"
                    )
                )
                assert delivery is not None
                assert delivery.house_id == house_id and delivery.chat_id == "777"
                assert delivery.status == "pending"
                inbox = await session.get(InboxEventRow, event_id)
                assert inbox is not None and inbox.status == "done"

            async with sessions.begin() as session:
                assert not await save_inbox_event(session, event.source_key, event, {}, NOW)
        finally:
            async with sessions.begin() as session:
                case_ids = select(CaseRow.id).where(CaseRow.house_id == house_id)
                await session.execute(
                    delete(OutboxDeliveryRow).where(OutboxDeliveryRow.house_id == house_id)
                )
                await session.execute(delete(AgentRunRow).where(AgentRunRow.house_id == house_id))
                await session.execute(delete(InboxEventRow).where(InboxEventRow.id == event_id))
                await session.execute(
                    delete(CaseOperationRow).where(CaseOperationRow.case_id.in_(case_ids))
                )
                await session.execute(
                    delete(CaseEventRow).where(CaseEventRow.case_id.in_(case_ids))
                )
                await session.execute(
                    delete(CaseMessageRow).where(CaseMessageRow.case_id.in_(case_ids))
                )
                await session.execute(delete(CaseRow).where(CaseRow.house_id == house_id))
                await session.execute(delete(ResidencyRow).where(ResidencyRow.id == residency_id))
                await session.execute(delete(ApartmentRow).where(ApartmentRow.id == apartment_id))
                await session.execute(delete(ResidentRow).where(ResidentRow.id == resident_id))
                await session.execute(delete(HouseRow).where(HouseRow.id == house_id))
