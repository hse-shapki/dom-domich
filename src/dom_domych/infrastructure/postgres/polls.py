"""Атомарное хранение опросов, ответов и событий в PostgreSQL."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import (
    EntityEventPayload,
    EventEnvelope,
    EventName,
    EventSource,
)
from dom_domych.domain.polls.models import (
    PollAnswer,
    PollDefinition,
    PollKind,
    PollMutation,
    PollOutcome,
    PollPolicy,
    PollState,
    PollStatus,
    VoteChoice,
)
from dom_domych.domain.polls.policy import (
    InitiativeOutcome,
    InitiativePolicy,
    ProblemOutcome,
    ProblemPolicy,
    ResolutionOutcome,
    ResolutionPolicy,
)
from dom_domych.domain.ports.core import JobIntent
from dom_domych.infrastructure.postgres.inbox import save_domain_event
from dom_domych.infrastructure.postgres.jobs import DueJob, PostgresJobQueue
from dom_domych.infrastructure.postgres.models import InboxEventRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.z_audience_models import AudienceMemberRow
from dom_domych.infrastructure.postgres.z_poll_models import (
    PollAnswerHistoryRow,
    PollAnswerRow,
    PollMemberRow,
    PollRow,
)


def _policy_data(policy: PollPolicy) -> dict[str, object]:
    common: dict[str, object] = {"revision": policy.revision, "demo": policy.demo}
    if isinstance(policy, ProblemPolicy):
        return {
            **common,
            "threshold_ratio": str(policy.threshold_ratio),
            "wait_microseconds": int(policy.wait_period / timedelta(microseconds=1)),
        }
    if isinstance(policy, InitiativePolicy):
        return {
            **common,
            "min_participation": str(policy.min_participation),
            "min_support_answered": str(policy.min_support_answered),
        }
    return {
        **common,
        "min_response_ratio": str(policy.min_response_ratio),
        "min_yes_answered": str(policy.min_yes_answered),
        "reopen_no_ratio": str(policy.reopen_no_ratio),
    }


def _read_policy(kind: PollKind, data: dict[str, object]) -> PollPolicy:
    revision, demo = str(data["revision"]), bool(data["demo"])
    if kind == PollKind.PROBLEM_CONFIRMATION:
        return ProblemPolicy(
            revision,
            Decimal(str(data["threshold_ratio"])),
            timedelta(microseconds=int(str(data["wait_microseconds"]))),
            demo,
        )
    if kind == PollKind.INITIATIVE_POSITION:
        return InitiativePolicy(
            revision,
            Decimal(str(data["min_participation"])),
            Decimal(str(data["min_support_answered"])),
            demo,
        )
    return ResolutionPolicy(
        revision,
        Decimal(str(data["min_response_ratio"])),
        Decimal(str(data["min_yes_answered"])),
        Decimal(str(data["reopen_no_ratio"])),
        demo,
    )


def _read_outcome(kind: PollKind, value: str | None) -> PollOutcome | None:
    if value is None:
        return None
    if kind == PollKind.PROBLEM_CONFIRMATION:
        return ProblemOutcome(value)
    if kind == PollKind.INITIATIVE_POSITION:
        return InitiativeOutcome(value)
    return ResolutionOutcome(value)


def _to_answer(row: PollAnswerRow | PollAnswerHistoryRow) -> PollAnswer:
    return PollAnswer(
        row.resident_id,
        VoteChoice(row.choice),
        row.source_event_id,
        row.received_at,
        row.revision,
    )


class PostgresPollRepository:
    """Все записи выполняются в session вызывающей UoW; без сетевого вызова под lock."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_definition(self, poll_id: UUID, house_id: UUID) -> PollDefinition | None:
        state = await self.get_state(poll_id, house_id)
        return state.definition if state is not None else None

    async def get_state(self, poll_id: UUID, house_id: UUID) -> PollState | None:
        row = await self.session.scalar(
            select(PollRow).where(PollRow.id == poll_id, PollRow.house_id == house_id)
        )
        return await self._load(row) if row is not None else None

    async def _load(self, row: PollRow) -> PollState:
        members = (
            await self.session.scalars(
                select(PollMemberRow.resident_id).where(PollMemberRow.poll_id == row.id)
            )
        ).all()
        answers = (
            await self.session.scalars(
                select(PollAnswerRow)
                .where(PollAnswerRow.poll_id == row.id)
                .order_by(PollAnswerRow.resident_id)
            )
        ).all()
        history = (
            await self.session.scalars(
                select(PollAnswerHistoryRow)
                .where(PollAnswerHistoryRow.poll_id == row.id)
                .order_by(PollAnswerHistoryRow.sequence)
            )
        ).all()
        kind = PollKind(row.kind)
        definition = PollDefinition(
            row.id,
            row.case_id,
            row.house_id,
            row.audience_id,
            kind,
            _read_policy(kind, row.policy),
            row.subject_revision,
            frozenset(members),
            row.opens_at,
            row.closes_at,
        )
        return PollState(
            definition=definition,
            answers=tuple(_to_answer(answer) for answer in answers),
            answer_history=tuple(_to_answer(answer) for answer in history),
            processed_event_ids=frozenset(answer.source_event_id for answer in history),
            status=PollStatus(row.status),
            version=row.version,
            outcome=_read_outcome(kind, row.outcome),
            threshold_emitted=row.threshold_emitted,
        )

    async def open_once(
        self,
        state: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> PollState:
        definition = state.definition
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid poll operation key")
        audience_members = frozenset(
            (
                await self.session.scalars(
                    select(AudienceMemberRow.resident_id).where(
                        AudienceMemberRow.audience_id == definition.audience_id,
                        AudienceMemberRow.house_id == definition.house_id,
                    )
                )
            ).all()
        )
        if (
            not audience_members
            or audience_members != definition.eligible_residents
            or set(notification_targets) != audience_members
            or len(notification_targets) != len(audience_members)
        ):
            raise ValueError("poll audience does not match frozen snapshot")
        inserted = await self.session.scalar(
            insert(PollRow)
            .values(
                id=definition.poll_id,
                case_id=definition.case_id,
                house_id=definition.house_id,
                audience_id=definition.audience_id,
                operation_key=operation_key,
                kind=definition.kind.value,
                policy=_policy_data(definition.policy),
                subject_revision=definition.subject_revision,
                opens_at=definition.opens_at,
                closes_at=definition.closes_at,
                status=state.status.value,
                version=state.version,
                outcome=None,
                threshold_emitted=False,
            )
            .on_conflict_do_nothing()
            .returning(PollRow.id)
        )
        if inserted is None:
            existing = await self.session.scalar(
                select(PollRow).where(
                    PollRow.house_id == definition.house_id,
                    PollRow.operation_key == operation_key,
                )
            )
            if existing is None:
                raise ValueError("poll already opened for this subject revision")
            loaded = await self._load(existing)
            before, now = loaded.definition, definition
            if (
                before.case_id,
                before.audience_id,
                before.kind,
                before.policy,
                before.subject_revision,
                before.eligible_residents,
            ) != (
                now.case_id,
                now.audience_id,
                now.kind,
                now.policy,
                now.subject_revision,
                now.eligible_residents,
            ):
                raise ValueError("operation key conflicts with another poll")
            return loaded
        await self.session.execute(
            insert(PollMemberRow),
            [
                {
                    "poll_id": definition.poll_id,
                    "house_id": definition.house_id,
                    "audience_id": definition.audience_id,
                    "resident_id": resident_id,
                }
                for resident_id in audience_members
            ],
        )
        await PostgresJobQueue(self.session).enqueue(
            JobIntent(
                house_id=definition.house_id,
                operation_key=f"poll:expire:{definition.poll_id}",
                event_name=EventName.POLL_EXPIRED.value,
                due_at=definition.closes_at,
                entity_id=definition.poll_id,
                expected_version=definition.subject_revision,
            )
        )
        return state

    async def record_answer_atomic(
        self,
        poll_id: UUID,
        house_id: UUID,
        actor_id: UUID,
        choice: VoteChoice,
        source_event_id: UUID,
        received_at: datetime,
    ) -> PollMutation:
        row = await self._locked(poll_id, house_id)
        current = await self._load(row)
        mutation = current.record_answer(actor_id, choice, source_event_id, received_at)
        if mutation.state == current:
            return mutation
        answer = next(item for item in mutation.state.answers if item.resident_id == actor_id)
        await self.session.execute(
            insert(PollAnswerRow)
            .values(
                poll_id=poll_id,
                resident_id=actor_id,
                choice=answer.choice.value,
                source_event_id=source_event_id,
                received_at=received_at,
                revision=answer.revision,
            )
            .on_conflict_do_update(
                index_elements=["poll_id", "resident_id"],
                set_={
                    "choice": answer.choice.value,
                    "source_event_id": source_event_id,
                    "received_at": received_at,
                    "revision": answer.revision,
                },
            )
        )
        self.session.add(
            PollAnswerHistoryRow(
                poll_id=poll_id,
                resident_id=actor_id,
                choice=answer.choice.value,
                source_event_id=source_event_id,
                received_at=received_at,
                revision=answer.revision,
            )
        )
        self._update_row(row, mutation.state)
        if "poll.threshold_reached" in mutation.events:
            await self._emit(row, EventName.POLL_THRESHOLD_REACHED, source_event_id, received_at)
        await self.session.flush()
        return mutation

    async def finalize_atomic(self, poll_id: UUID, house_id: UUID, now: datetime) -> PollMutation:
        row = await self._locked(poll_id, house_id)
        current = await self._load(row)
        if current.status == PollStatus.OPEN:
            pending = await self.session.scalar(
                select(InboxEventRow.id)
                .where(
                    InboxEventRow.event_name == EventName.CALLBACK_RECEIVED.value,
                    InboxEventRow.received_at < row.closes_at,
                    InboxEventRow.status.in_(("pending", "processing")),
                    or_(InboxEventRow.house_id == house_id, InboxEventRow.house_id.is_(None)),
                )
                .limit(1)
            )
            if pending is not None:
                raise ValueError("POLL_INBOX_NOT_DRAINED")
        mutation = current.finalize(now)
        if mutation.state != current:
            self._update_row(row, mutation.state)
            await self._emit(row, EventName.POLL_EXPIRED, poll_id, now)
            await self.session.flush()
        return mutation

    async def cancel_atomic(self, poll_id: UUID, house_id: UUID) -> PollMutation:
        row = await self._locked(poll_id, house_id)
        current = await self._load(row)
        mutation = current.cancel()
        if mutation.state != current:
            self._update_row(row, mutation.state)
            await PostgresPollActionStore(self.session).revoke_poll(poll_id, house_id)
            await self.session.flush()
        return mutation

    async def _locked(self, poll_id: UUID, house_id: UUID) -> PollRow:
        row = await self.session.scalar(
            select(PollRow)
            .where(PollRow.id == poll_id, PollRow.house_id == house_id)
            .with_for_update()
        )
        if row is None:
            raise ValueError("poll is missing or belongs to another house")
        return row

    @staticmethod
    def _update_row(row: PollRow, state: PollState) -> None:
        row.status = state.status.value
        row.version = state.version
        row.outcome = state.outcome.value if state.outcome is not None else None
        row.threshold_emitted = state.threshold_emitted

    async def _emit(
        self, row: PollRow, name: EventName, causation_id: UUID, occurred_at: datetime
    ) -> None:
        await save_domain_event(
            self.session,
            EventEnvelope(
                event_id=uuid4(),
                source=EventSource.DOMAIN,
                source_key=f"poll:{row.id}:{name.value}",
                name=name,
                occurred_at=occurred_at,
                received_at=occurred_at,
                correlation_id=causation_id,
                house_id=row.house_id,
                entity=EntityEventPayload(
                    entity_id=row.id,
                    entity_version=row.version,
                    case_id=row.case_id,
                    causation_id=causation_id,
                ),
            ),
        )


class PostgresPollRevisionReader:
    """Ответы не делают deadline устаревшим; закрытие или отмена делают."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def current_version(self, job: DueJob) -> int | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(PollRow).where(PollRow.id == job.entity_id, PollRow.house_id == job.house_id)
            )
            return row.subject_revision if row is not None and row.status == "open" else None
