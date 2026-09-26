"""K08: конкурентные сообщения и версии на мигрированной PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from dom_domych.agent.contracts import (
    CaseAttachMessage,
    CaseCreate,
    CaseKind,
    CaseSearch,
    TrustedContext,
)
from dom_domych.application.cases.candidates import CandidateService
from dom_domych.application.cases.service import CaseService
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.infrastructure.postgres.case_candidates import PostgresCaseReader
from dom_domych.infrastructure.postgres.case_models import (
    CaseEventRow,
    CaseMessageRow,
    CaseOperationRow,
    CaseRow,
)
from dom_domych.infrastructure.postgres.case_writer import PostgresCaseWriter
from dom_domych.infrastructure.postgres.models import HouseRow, ResidentRow
from dom_domych.infrastructure.postgres.session import database_lifespan


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


def _context(house_id: UUID, actor_id: UUID) -> TrustedContext:
    return TrustedContext(
        run_id=uuid4(),
        event_id=uuid4(),
        house_id=house_id,
        actor_id=actor_id,
        principal_type=PrincipalType.RESIDENT,
        capabilities=frozenset({"case.read", "case.write"}),
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


def _create(context: TrustedContext, *, object_name: str = "лампа") -> CaseCreate:
    return CaseCreate(
        kind=CaseKind.PROBLEM,
        title="Темно на лестнице",
        description="Не горит лампа на третьем этаже",
        entrance=1,
        floor=3,
        object_name=object_name,
        source_message_id=context.event_id,
        operation_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_twelve_messages_create_one_case_and_cross_house_is_hidden() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL needs a migrated PostgreSQL database")
    house_id, other_house, actor_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            session.add_all(
                [
                    HouseRow(id=house_id, address="K08 дом 1", timezone="UTC", demo=True),
                    HouseRow(id=other_house, address="K08 дом 2", timezone="UTC", demo=True),
                    ResidentRow(id=actor_id, display_name="Житель K08", active_house_id=house_id),
                ]
            )
        try:
            service = CaseService(
                CandidateService(PostgresCaseReader(sessions)),
                PostgresCaseWriter(sessions),
                FixedClock(now),
            )
            contexts = [_context(house_id, actor_id) for _ in range(12)]
            commands = [_create(context) for context in contexts]
            outcomes = await asyncio.gather(
                *(
                    service.create(command, context)
                    for command, context in zip(commands, contexts, strict=True)
                ),
                return_exceptions=True,
            )
            created = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
            assert len(created) == 1
            assert all(
                str(outcome) == "CANDIDATES_CHANGED"
                for outcome in outcomes
                if isinstance(outcome, BaseException)
            )
            case = created[0]
            assert case.version == 1
            origin = next(
                index
                for index, context in enumerate(contexts)
                if f"event:{context.event_id}" == case.source_refs[0]
            )
            assert await service.create(commands[origin], contexts[origin]) == case
            with pytest.raises(ValueError, match="CONFLICT"):
                await service.create(
                    commands[origin].model_copy(update={"title": "Сломана дверь"}),
                    contexts[origin],
                )
            with pytest.raises(PermissionError, match="SOURCE_EVENT_MISMATCH"):
                await service.create(commands[origin], _context(house_id, actor_id))
            first_attach: tuple[CaseAttachMessage, TrustedContext] | None = None
            for context in contexts:
                if f"event:{context.event_id}" == created[0].source_refs[0]:
                    continue
                command = CaseAttachMessage(
                    case_id=case.case_id,
                    message_id=context.event_id,
                    expected_version=case.version,
                    operation_id=uuid4(),
                )
                if first_attach is None:
                    first_attach = (command, context)
                case = await service.attach_message(command, context)
            assert case.version == 12
            assert first_attach is not None
            assert (await service.attach_message(*first_attach)).version == 2
            stale_context = _context(house_id, actor_id)
            with pytest.raises(ValueError, match="VERSION_CONFLICT"):
                await service.attach_message(
                    CaseAttachMessage(
                        case_id=case.case_id,
                        message_id=stale_context.event_id,
                        expected_version=1,
                        operation_id=uuid4(),
                    ),
                    stale_context,
                )
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(CaseRow)
                        .where(CaseRow.house_id == house_id)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(CaseMessageRow)
                        .where(CaseMessageRow.case_id == case.case_id)
                    )
                    == 12
                )
            second_case = await service.create(
                _create(contexts[origin], object_name="лифт"), contexts[origin]
            )
            assert second_case.case_id != case.case_id
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(CaseMessageRow)
                        .where(CaseMessageRow.message_id == contexts[origin].event_id)
                    )
                    == 2
                )
            assert await service.get(case.case_id, _context(other_house, actor_id)) is None
            assert (
                await service.search(
                    CaseSearch(query="не горит лампа", entrance=2, object_name="лампа"),
                    _context(house_id, actor_id),
                )
                == ()
            )
            async with sessions.begin() as session:
                row = await session.get(CaseRow, case.case_id)
                assert row is not None
                row.status = "closed"
                row.closed_at = now
            recurrence_context = _context(house_id, actor_id)
            recurrence = await service.create(_create(recurrence_context), recurrence_context)
            async with sessions() as session:
                row = await session.get(CaseRow, recurrence.case_id)
                assert row is not None and row.recurrence_of == case.case_id
        finally:
            async with sessions.begin() as session:
                await session.execute(
                    delete(CaseOperationRow).where(CaseOperationRow.house_id == house_id)
                )
                await session.execute(delete(CaseEventRow).where(CaseEventRow.house_id == house_id))
                await session.execute(
                    delete(CaseMessageRow).where(CaseMessageRow.house_id == house_id)
                )
                await session.execute(delete(CaseRow).where(CaseRow.house_id == house_id))
                await session.execute(delete(ResidentRow).where(ResidentRow.id == actor_id))
                await session.execute(
                    delete(HouseRow).where(HouseRow.id.in_([house_id, other_house]))
                )
