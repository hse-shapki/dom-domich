"""Атомарная редакция инициативы вместе с заменой опроса."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.initiatives.followup import demo_reminder_policy
from dom_domych.contracts.events import EventName
from dom_domych.domain.initiatives.models import (
    InitiativeConflict,
    InitiativeForbidden,
    InitiativeRevision,
    InitiativeState,
)
from dom_domych.domain.polls.models import PollState
from dom_domych.domain.ports.core import JobIntent
from dom_domych.infrastructure.postgres.case_models import CaseMessageRow, CaseRow
from dom_domych.infrastructure.postgres.jobs import PostgresJobQueue
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.z_initiative_models import (
    InitiativeOperationRow,
    InitiativeRevisionRow,
    InitiativeRow,
)


class PostgresInitiativeRepository:
    """Сериализует редакции под case/initiative lock и использует общий poll UoW."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, case_id: UUID, house_id: UUID) -> InitiativeState:
        async with self.sessions() as session:
            return await self._load(session, case_id, house_id)

    async def get_operation_result(
        self, house_id: UUID, operation_key: str
    ) -> InitiativeState | None:
        async with self.sessions() as session:
            return await self._operation_result(session, house_id, operation_key)

    async def create_and_open_atomic(
        self,
        state: InitiativeState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> InitiativeState:
        async with self.sessions.begin() as session:
            await self._guard_case(session, state)
            repeated = await self._operation_result(session, state.house_id, operation_key)
            if repeated is not None:
                if (
                    repeated.case_id != state.case_id
                    or repeated.current.wording != state.current.wording
                    or repeated.current.audience_id != state.current.audience_id
                    or repeated.current.revision != state.current.revision
                ):
                    raise InitiativeConflict("operation key was used for another initiative")
                return repeated
            existing = await session.get(InitiativeRow, state.case_id)
            if existing is not None:
                raise InitiativeConflict("initiative already exists")
            session.add(
                InitiativeRow(
                    case_id=state.case_id,
                    house_id=state.house_id,
                    author_id=state.author_id,
                    case_version=state.case_version,
                    current_revision=1,
                )
            )
            await session.flush()
            await PostgresPollRepository(session).open_once(
                poll, notification_targets, f"initiative:poll:{operation_key}"
            )
            await self._schedule_reminders(session, poll)
            self._add_revision(session, state.current, state.case_id, state.house_id)
            self._add_operation(session, state, operation_key)
            await session.flush()
            return state

    async def revise_and_replace_poll_atomic(
        self,
        previous: InitiativeState,
        updated: InitiativeState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> InitiativeState:
        async with self.sessions.begin() as session:
            await self._guard_case(session, updated)
            row = await session.scalar(
                select(InitiativeRow)
                .where(
                    InitiativeRow.case_id == updated.case_id,
                    InitiativeRow.house_id == updated.house_id,
                )
                .with_for_update()
            )
            if row is None:
                raise InitiativeConflict("initiative is missing")
            repeated = await self._operation_result(session, updated.house_id, operation_key)
            if repeated is not None:
                if (
                    repeated.case_id != updated.case_id
                    or repeated.current.wording != updated.current.wording
                    or repeated.current.audience_id != updated.current.audience_id
                    or repeated.current.revision != updated.current.revision
                ):
                    raise InitiativeConflict("operation key was used for another revision")
                return repeated
            if row.current_revision != previous.current.revision:
                raise InitiativeConflict("initiative revision changed concurrently")
            current = await self._load(session, updated.case_id, updated.house_id)
            if current != previous:
                raise InitiativeConflict("initiative changed concurrently")
            await PostgresPollRepository(session).cancel_atomic(
                previous.current.poll_id, updated.house_id
            )
            await PostgresPollRepository(session).open_once(
                poll, notification_targets, f"initiative:poll:{operation_key}"
            )
            await self._schedule_reminders(session, poll)
            self._add_revision(session, updated.current, updated.case_id, updated.house_id)
            row.current_revision = updated.current.revision
            self._add_operation(session, updated, operation_key)
            await session.flush()
            return updated

    @staticmethod
    async def _schedule_reminders(session: AsyncSession, poll: PollState) -> None:
        definition = poll.definition
        if not definition.eligible_residents:
            return
        policy = demo_reminder_policy()
        window = definition.closes_at - definition.opens_at
        for number in (1, 2):
            due_at = definition.opens_at + window * number / 3
            if due_at >= definition.closes_at - policy.stop_before_deadline:
                continue
            await PostgresJobQueue(session).enqueue(
                JobIntent(
                    house_id=definition.house_id,
                    operation_key=f"initiative:reminder:{definition.poll_id}:{number}",
                    event_name=EventName.INITIATIVE_REMINDER_DUE.value,
                    due_at=due_at,
                    entity_id=definition.poll_id,
                    expected_version=definition.subject_revision,
                )
            )

    @staticmethod
    async def _guard_case(session: AsyncSession, state: InitiativeState) -> None:
        case = await session.scalar(
            select(CaseRow)
            .where(CaseRow.id == state.case_id, CaseRow.house_id == state.house_id)
            .with_for_update()
        )
        if case is None or case.kind != "initiative":
            raise InitiativeForbidden("initiative case is missing or belongs to another house")
        author_id = await session.scalar(
            select(CaseMessageRow.actor_id)
            .where(
                CaseMessageRow.case_id == state.case_id,
                CaseMessageRow.house_id == state.house_id,
                CaseMessageRow.relation == "origin",
            )
            .limit(1)
        )
        if author_id != state.author_id:
            raise InitiativeForbidden("only initiative author may change wording")
        if case.version != state.case_version:
            raise InitiativeConflict("case version changed")

    @staticmethod
    def _add_revision(
        session: AsyncSession, revision: InitiativeRevision, case_id: UUID, house_id: UUID
    ) -> None:
        session.add(
            InitiativeRevisionRow(
                case_id=case_id,
                house_id=house_id,
                revision=revision.revision,
                wording=revision.wording,
                audience_id=revision.audience_id,
                poll_id=revision.poll_id,
                created_at=revision.created_at,
            )
        )

    @staticmethod
    def _add_operation(session: AsyncSession, state: InitiativeState, operation_key: str) -> None:
        if not operation_key or len(operation_key) > 220:
            raise ValueError("invalid initiative operation key")
        session.add(
            InitiativeOperationRow(
                id=uuid4(),
                house_id=state.house_id,
                operation_key=operation_key,
                case_id=state.case_id,
                revision=state.current.revision,
                case_version=state.case_version,
            )
        )

    @staticmethod
    async def _operation_result(
        session: AsyncSession, house_id: UUID, operation_key: str
    ) -> InitiativeState | None:
        operation = await session.scalar(
            select(InitiativeOperationRow).where(
                InitiativeOperationRow.house_id == house_id,
                InitiativeOperationRow.operation_key == operation_key,
            )
        )
        if operation is None:
            return None
        return await PostgresInitiativeRepository._load(
            session,
            operation.case_id,
            house_id,
            up_to_revision=operation.revision,
            case_version=operation.case_version,
        )

    @staticmethod
    async def _load(
        session: AsyncSession,
        case_id: UUID,
        house_id: UUID,
        *,
        up_to_revision: int | None = None,
        case_version: int | None = None,
    ) -> InitiativeState:
        row = await session.scalar(
            select(InitiativeRow).where(
                InitiativeRow.case_id == case_id, InitiativeRow.house_id == house_id
            )
        )
        if row is None:
            raise ValueError("initiative not found in this house")
        revision_limit = up_to_revision or row.current_revision
        revisions = (
            await session.scalars(
                select(InitiativeRevisionRow)
                .where(
                    InitiativeRevisionRow.case_id == case_id,
                    InitiativeRevisionRow.house_id == house_id,
                    InitiativeRevisionRow.revision <= revision_limit,
                )
                .order_by(InitiativeRevisionRow.revision)
            )
        ).all()
        return InitiativeState(
            case_id=row.case_id,
            house_id=row.house_id,
            author_id=row.author_id,
            case_version=case_version or row.case_version,
            revisions=tuple(
                InitiativeRevision(
                    revision=item.revision,
                    wording=item.wording,
                    audience_id=item.audience_id,
                    poll_id=item.poll_id,
                    created_at=item.created_at,
                )
                for item in revisions
            ),
        )
