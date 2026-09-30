"""Z05: настоящий actor MAX проходит через Z callback к PostgreSQL-голосу."""

import json
import os
from asyncio import gather
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from dom_domych.application.audiences.service import AudienceService
from dom_domych.application.cards.production import PostgresPublicCards
from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.application.polls.callback import CallbackStatus, StoredPollAction
from dom_domych.application.polls.production import PostgresPollCallbackProcessor
from dom_domych.application.polls.service import PollService
from dom_domych.contracts.events import CallbackPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.audiences.models import AudienceScope, ScopeKind
from dom_domych.domain.polls.models import PollKind, VoteChoice
from dom_domych.domain.polls.policy import demo_problem_policy
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.house_context import PostgresHouseContext
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow, ResidentRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_poll_models import PollAnswerHistoryRow, PollAnswerRow
from scripts.seed_demo_house import seed_demo_house
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO, synthetic_id


@dataclass(frozen=True)
class Context:
    house_id: UUID


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


def callback_event(
    token: str, user_id: str, chat_id: str, *, received_at: datetime | None = None
) -> EventEnvelope:
    event_id = uuid4()
    received_at = received_at or FixedClock().now() + timedelta(minutes=1)
    return EventEnvelope(
        event_id=event_id,
        source=EventSource.MAX,
        source_key=f"z05:callback:{event_id}",
        name=EventName.CALLBACK_RECEIVED,
        occurred_at=received_at,
        received_at=received_at,
        correlation_id=event_id,
        actor_user_id=user_id,
        callback=CallbackPayload(
            callback_id=f"callback-{event_id}",
            sender_user_id=user_id,
            action_token=token,
            chat_id=chat_id,
        ),
    )


@pytest.mark.asyncio
async def test_callback_records_only_verified_actor_and_rejects_stale_action() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Z05 requires a dedicated migrated PostgreSQL test database")
    clock = FixedClock()
    chat_one, chat_two = "-" + str(uuid4().int)[:17], "-" + str(uuid4().int)[:17]
    user_one, user_two, user_outside, user_concurrent = (str(uuid4().int)[:18] for _ in range(4))
    acknowledged: list[tuple[str, dict[str, object]]] = []
    sent: list[tuple[str, str, dict[str, str], dict[str, object]]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/answers":
            acknowledged.append((request.url.params["callback_id"], body))
            return httpx.Response(200, json={"success": True})
        sent.append((request.method, request.url.path, dict(request.url.params), body))
        if request.method == "POST":
            return httpx.Response(200, json={"message": {"body": {"mid": str(uuid4())}}})
        return httpx.Response(200, json={"success": True})

    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await seed_demo_house(session)
            case_id = uuid4()
            session.add(
                CaseRow(
                    id=case_id,
                    house_id=HOUSE_ONE,
                    kind="problem",
                    title="Callback тест",
                    description="Тест",
                    status="collecting",
                    version=1,
                    created_at=clock.now(),
                )
            )
            audience = await AudienceService(
                PostgresHouseContext(session, clock), PostgresAudienceRepository(session), clock
            ).resolve(
                AudienceScope(ScopeKind.FLOOR, entrance=2, floor=5),
                Context(HOUSE_ONE),
                operation_key=f"z05:audience:{case_id}",
            )
            poll = await PollService(PostgresPollRepository(session), clock).open(
                case_id,
                audience,
                PollKind.PROBLEM_CONFIRMATION,
                demo_problem_policy(),
                1,
                Context(HOUSE_ONE),
                operation_key=f"z05:poll:{case_id}",
            )
            first, second = audience.members[:2]
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id == first.resident_id)
                .values(max_user_id=user_one)
            )
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id == second.resident_id)
                .values(max_user_id=user_two)
            )
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id == synthetic_id("resident-17"))
                .values(max_user_id=user_outside)
            )
            await session.execute(
                update(ResidentRow)
                .where(ResidentRow.id == audience.members[2].resident_id)
                .values(max_user_id=user_concurrent)
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_ONE).values(max_chat_id=chat_one)
            )
            await session.execute(
                update(HouseRow).where(HouseRow.id == HOUSE_TWO).values(max_chat_id=chat_two)
            )
            token = await PostgresPollActionStore(session).create(
                StoredPollAction(
                    poll_id=poll.definition.poll_id,
                    house_id=HOUSE_ONE,
                    audience_id=audience.audience_id,
                    subject_revision=1,
                    choice=VoteChoice.YES,
                    expires_at=poll.definition.closes_at,
                    bound_resident_id=first.resident_id,
                )
            )
            no_token = await PostgresPollActionStore(session).create(
                StoredPollAction(
                    poll_id=poll.definition.poll_id,
                    house_id=HOUSE_ONE,
                    audience_id=audience.audience_id,
                    subject_revision=1,
                    choice=VoteChoice.NO,
                    expires_at=poll.definition.closes_at,
                )
            )
        base_id = await PostgresPublicCards(sessions, clock).publish_problem(
            poll.definition.poll_id, HOUSE_ONE
        )
        async with sessions.begin() as session:
            await session.execute(
                update(OutboxDeliveryRow)
                .where(OutboxDeliveryRow.house_id == HOUSE_ONE)
                .values(status="sent")
            )
            base = await session.get(OutboxDeliveryRow, base_id)
            assert base is not None
            base.max_message_id = "public-card"
            invite = await session.scalar(
                select(OutboxDeliveryRow).where(
                    OutboxDeliveryRow.operation_key
                    == f"poll:invite:{poll.definition.poll_id}:{first.resident_id}"
                )
            )
            assert invite is not None
            invite.max_message_id = "private-invite"
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="https://platform-api2.max.ru"
        ) as http:
            max_client = MaxApiClient(http, "test-token")
            processor = PostgresPollCallbackProcessor(sessions, max_client, clock)
            good = callback_event(token, user_one, chat_one)
            assert (await processor.process(good)).status == CallbackStatus.RECORDED
            worker = DeliveryWorker(sessions, max_client, clock, "z05-delivery")
            assert await worker.run_once() is True
            assert await worker.run_once() is True
            assert await worker.run_once() is False
            assert {(method, path) for method, path, _, _ in sent} == {("PUT", "/messages")}
            assert any(params.get("message_id") == "public-card" for _, _, params, _ in sent)
            assert any(params.get("message_id") == "private-invite" for _, _, params, _ in sent)
            assert (await processor.process(good)).status == CallbackStatus.DUPLICATE
            assert (
                await processor.process(callback_event(token, user_one, chat_one))
            ).status == CallbackStatus.DUPLICATE
            assert (
                await processor.process(callback_event(no_token, user_one, chat_one))
            ).status == CallbackStatus.CHANGED
            assert (
                await processor.process(callback_event(no_token, user_outside, chat_one))
            ).status == CallbackStatus.NOT_ALLOWED
            assert (
                await processor.process(callback_event(token, user_two, chat_one))
            ).status == CallbackStatus.NOT_ALLOWED
            assert (
                await processor.process(callback_event(token, user_one, chat_two))
            ).status == CallbackStatus.NOT_ALLOWED
            assert (
                await processor.process(callback_event("unknown-token", user_one, chat_one))
            ).status == CallbackStatus.UNKNOWN_ACTION
            assert (
                await processor.process(callback_event("unknown-token", "999999999", chat_one))
            ).status == CallbackStatus.UNKNOWN_ACTION
            async with sessions.begin() as session:
                state = await PostgresPollRepository(session).get_state(
                    poll.definition.poll_id, HOUSE_ONE
                )
                assert state is not None and state.tally.yes == 0 and state.tally.no == 1
                answers = (
                    await session.scalars(
                        select(PollAnswerRow).where(
                            PollAnswerRow.poll_id == poll.definition.poll_id
                        )
                    )
                ).all()
                history = (
                    await session.scalars(
                        select(PollAnswerHistoryRow).where(
                            PollAnswerHistoryRow.poll_id == poll.definition.poll_id
                        )
                    )
                ).all()
                assert len(answers) == 1 and len(history) == 2
                feedback = (
                    await session.scalars(
                        select(OutboxDeliveryRow).where(
                            OutboxDeliveryRow.operation_key.like("poll:feedback:%")
                        )
                    )
                ).all()
                assert feedback == []
                edits = (
                    await session.scalars(
                        select(OutboxDeliveryRow).where(
                            OutboxDeliveryRow.edit_key == f"problem:{case_id}"
                        )
                    )
                ).all()
                assert len(edits) == 2
                assert "Поддержали 0 из 12 жителей" in next(
                    row.text for row in edits if row.status == "pending"
                )
            concurrent = await gather(
                processor.process(callback_event(no_token, user_concurrent, chat_one)),
                processor.process(callback_event(no_token, user_concurrent, chat_one)),
            )
            assert {item.status for item in concurrent} == {
                CallbackStatus.RECORDED,
                CallbackStatus.DUPLICATE,
            }
            assert (
                await processor.process(
                    callback_event(
                        token,
                        user_one,
                        chat_one,
                        received_at=poll.definition.closes_at,
                    )
                )
            ).status == CallbackStatus.LATE
            async with sessions.begin() as session:
                for member in audience.members[3:6]:
                    await PostgresPollRepository(session).record_answer_atomic(
                        poll.definition.poll_id,
                        HOUSE_ONE,
                        member.resident_id,
                        VoteChoice.YES,
                        uuid4(),
                        clock.now() + timedelta(minutes=1),
                    )
            assert (
                await processor.process(callback_event(no_token, user_one, chat_one))
            ).status == CallbackStatus.CLOSED
            async with sessions.begin() as session:
                await PostgresPollActionStore(session).revoke_poll(
                    poll.definition.poll_id, HOUSE_ONE
                )
            assert (
                await processor.process(callback_event(token, user_one, chat_one))
            ).status == CallbackStatus.STALE
        assert len(acknowledged) == 14
        assert [body["notification"] for _, body in acknowledged] == [
            "Вы поддержали.",
            "Вы поддержали.",
            "Вы поддержали.",
            "Вы не поддержали.",
            "Этот опрос доступен только жителям затронутой части дома.",
            "Этот опрос доступен только жителям затронутой части дома.",
            "Этот опрос доступен только жителям затронутой части дома.",
            "Кнопка устарела. Откройте актуальную карточку.",
            "Кнопка устарела. Откройте актуальную карточку.",
            "Вы не поддержали.",
            "Вы не поддержали.",
            "Время голосования истекло.",
            "Опрос уже завершён.",
            "Кнопка устарела. Откройте актуальную карточку.",
        ]
        async with sessions.begin() as session:
            await session.execute(
                update(ResidentRow)
                .where(
                    ResidentRow.id.in_(
                        (
                            first.resident_id,
                            second.resident_id,
                            audience.members[2].resident_id,
                            synthetic_id("resident-17"),
                        )
                    )
                )
                .values(max_user_id=None)
            )
            await session.execute(
                update(HouseRow)
                .where(HouseRow.id.in_((HOUSE_ONE, HOUSE_TWO)))
                .values(max_chat_id=None)
            )
