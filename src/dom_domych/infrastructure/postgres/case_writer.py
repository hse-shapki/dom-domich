"""K08: атомарные операции дела с повторной проверкой кандидатов под lock."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.contracts import (
    CaseAttachMessage,
    CaseCreate,
    CaseKind,
    CaseView,
    TrustedContext,
)
from dom_domych.infrastructure.postgres.case_models import (
    CaseEventRow,
    CaseMessageRow,
    CaseOperationRow,
    CaseRow,
)


def _view(row: CaseRow, refs: tuple[str, ...]) -> CaseView:
    return CaseView(
        case_id=row.id,
        version=row.version,
        kind=CaseKind(row.kind),
        title=row.title,
        status=row.status,
        source_refs=refs,
    )


def _command_hash(command: BaseModel, context: TrustedContext) -> str:
    payload = {
        "type": type(command).__name__,
        "command": command.model_dump(mode="json"),
        "actor_id": str(context.actor_id),
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class PostgresCaseWriter:
    """Advisory lock только на короткую транзакцию; LLM/HTTP сюда не входят."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    async def _lock(session: AsyncSession, scope: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": scope},
        )

    @staticmethod
    async def _prior(
        session: AsyncSession, house_id: UUID, operation_id: UUID, command_hash: str
    ) -> CaseView | None:
        row = await session.get(CaseOperationRow, (house_id, operation_id))
        if row is not None and row.command_hash != command_hash:
            raise ValueError("CONFLICT")
        return (
            CaseView.model_validate_json(json.dumps(row.result_view)) if row is not None else None
        )

    async def create_case(
        self, command: CaseCreate, context: TrustedContext, now: datetime
    ) -> CaseView:
        scope = (
            f"{context.house_id}:{command.kind.value}:{command.entrance}:"
            f"{command.floor}:{(command.object_name or command.title).casefold()}"
        )
        command_hash = _command_hash(command, context)
        async with self.sessions.begin() as session:
            await self._lock(session, f"operation:{context.house_id}:{command.operation_id}")
            await self._lock(session, scope)
            prior = await self._prior(session, context.house_id, command.operation_id, command_hash)
            if prior is not None:
                return prior
            same = select(CaseRow).where(
                CaseRow.house_id == context.house_id,
                CaseRow.kind == command.kind.value,
                CaseRow.entrance == command.entrance,
                CaseRow.floor == command.floor,
            )
            if command.object_name is None:
                same = same.where(
                    CaseRow.object_name.is_(None),
                    func.lower(CaseRow.title) == command.title.casefold(),
                )
            else:
                same = same.where(func.lower(CaseRow.object_name) == command.object_name.casefold())
            matches = (await session.scalars(same.order_by(CaseRow.created_at.desc()))).all()
            if any(row.status != "closed" for row in matches):
                raise ValueError("CANDIDATES_CHANGED")
            recent = next(
                (
                    row
                    for row in matches
                    if row.closed_at is not None and row.closed_at >= now - timedelta(days=30)
                ),
                None,
            )
            row = CaseRow(
                id=uuid4(),
                house_id=context.house_id,
                kind=command.kind.value,
                title=command.title,
                description=command.description,
                entrance=command.entrance,
                floor=command.floor,
                object_name=command.object_name,
                status="detected",
                version=1,
                created_at=now,
                closed_at=None,
                recurrence_of=recent.id if recent is not None else None,
                embedding=None,
                embedding_revision=None,
            )
            session.add(row)
            await session.flush()
            assert context.actor_id is not None
            session.add(
                CaseMessageRow(
                    case_id=row.id,
                    house_id=context.house_id,
                    message_id=command.source_message_id,
                    actor_id=context.actor_id,
                    relation="origin",
                    linked_at=now,
                )
            )
            view = _view(row, (f"event:{command.source_message_id}",))
            session.add(
                CaseEventRow(
                    id=uuid4(),
                    case_id=row.id,
                    house_id=context.house_id,
                    event_type="case.created",
                    before_version=None,
                    after_version=1,
                    actor_id=context.actor_id,
                    source_message_id=command.source_message_id,
                    operation_id=command.operation_id,
                    occurred_at=now,
                    facts={
                        "recurrence_of": str(recent.id) if recent is not None else None,
                        "kind": command.kind.value,
                    },
                )
            )
            session.add(
                CaseOperationRow(
                    house_id=context.house_id,
                    operation_id=command.operation_id,
                    case_id=row.id,
                    command_hash=command_hash,
                    result_view=view.model_dump(mode="json"),
                )
            )
            return view

    async def attach_message(
        self, command: CaseAttachMessage, context: TrustedContext, now: datetime
    ) -> CaseView:
        command_hash = _command_hash(command, context)
        async with self.sessions.begin() as session:
            await self._lock(session, f"operation:{context.house_id}:{command.operation_id}")
            prior = await self._prior(session, context.house_id, command.operation_id, command_hash)
            if prior is not None:
                return prior
            row = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == command.case_id, CaseRow.house_id == context.house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("CASE_NOT_FOUND")
            if row.version != command.expected_version:
                raise ValueError("VERSION_CONFLICT")
            if row.status == "closed":
                raise ValueError("INVALID_STATE")
            link = await session.get(CaseMessageRow, (row.id, command.message_id))
            if link is not None:
                raise ValueError("MESSAGE_ALREADY_ATTACHED")
            assert context.actor_id is not None
            session.add(
                CaseMessageRow(
                    case_id=row.id,
                    house_id=context.house_id,
                    message_id=command.message_id,
                    actor_id=context.actor_id,
                    relation="additional",
                    linked_at=now,
                )
            )
            old_version = row.version
            row.version += 1
            view = _view(row, (f"event:{command.message_id}",))
            session.add(
                CaseEventRow(
                    id=uuid4(),
                    case_id=row.id,
                    house_id=context.house_id,
                    event_type="case.message_attached",
                    before_version=old_version,
                    after_version=row.version,
                    actor_id=context.actor_id,
                    source_message_id=command.message_id,
                    operation_id=command.operation_id,
                    occurred_at=now,
                    facts={},
                )
            )
            session.add(
                CaseOperationRow(
                    house_id=context.house_id,
                    operation_id=command.operation_id,
                    case_id=row.id,
                    command_hash=command_hash,
                    result_view=view.model_dump(mode="json"),
                )
            )
            return view
