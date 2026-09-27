"""Напоминания неответившим и итог позиции в общей PostgreSQL UoW."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.initiatives.followup import InitiativeDecision, ReminderPolicy
from dom_domych.domain.initiatives.models import InitiativeConflict
from dom_domych.domain.polls.models import PollStatus
from dom_domych.domain.polls.policy import InitiativeOutcome
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.models import HouseRow, ResidencyRow, ResidentRow
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.z_followup_models import (
    InitiativeDecisionRow,
    InitiativeReminderBatchRow,
    InitiativeReminderRow,
)
from dom_domych.infrastructure.postgres.z_initiative_models import (
    InitiativeRevisionRow,
    InitiativeRow,
)
from dom_domych.infrastructure.postgres.z_poll_models import PollRow


async def _currently_reachable(
    session: AsyncSession, house_id: UUID, resident_ids: tuple[UUID, ...], now: datetime
) -> tuple[UUID, ...]:
    if not resident_ids:
        return ()
    rows = (
        await session.scalars(
            select(ResidentRow.id)
            .join(ResidencyRow, ResidencyRow.resident_id == ResidentRow.id)
            .where(
                ResidentRow.id.in_(resident_ids),
                ResidentRow.max_user_id.is_not(None),
                ResidentRow.dm_reachable.is_(True),
                ResidencyRow.house_id == house_id,
                ResidencyRow.confirmed.is_(True),
                ResidencyRow.adult.is_(True),
                ResidencyRow.valid_from <= now,
                or_(ResidencyRow.valid_until.is_(None), ResidencyRow.valid_until > now),
            )
        )
    ).all()
    return tuple(sorted(set(rows), key=lambda item: item.bytes))


class PostgresCurrentDeliveryRights:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def filter_reachable(
        self, house_id: UUID, resident_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        async with self.sessions() as session:
            return await _currently_reachable(session, house_id, resident_ids, self.clock.now())


class PostgresInitiativeFollowupRepository:
    """Сверяет права и версию ещё раз под poll lock перед каждым outbox intent."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def enqueue_reminders_atomic(
        self,
        poll_id: UUID,
        house_id: UUID,
        expected_poll_version: int,
        candidate_ids: tuple[UUID, ...],
        now: datetime,
        policy: ReminderPolicy,
        operation_key: str,
    ) -> tuple[UUID, ...]:
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid reminder operation key")
        async with self.sessions.begin() as session:
            poll_row = await session.scalar(
                select(PollRow)
                .where(PollRow.id == poll_id, PollRow.house_id == house_id)
                .with_for_update()
            )
            if poll_row is None:
                raise InitiativeConflict("initiative poll is missing")
            existing = await session.scalar(
                select(InitiativeReminderBatchRow).where(
                    InitiativeReminderBatchRow.house_id == house_id,
                    InitiativeReminderBatchRow.operation_key == operation_key,
                )
            )
            if existing is not None:
                if existing.poll_id != poll_id:
                    raise InitiativeConflict("reminder operation key conflict")
                return tuple(UUID(value) for value in existing.targets)
            poll = await PostgresPollRepository(session).get_state(poll_id, house_id)
            if (
                poll is None
                or poll.version != expected_poll_version
                or poll.status != PollStatus.OPEN
                or now >= poll.definition.closes_at - policy.stop_before_deadline
            ):
                raise InitiativeConflict("poll changed while planning reminders")
            revision = await session.scalar(
                select(InitiativeRevisionRow)
                .join(
                    InitiativeRow,
                    (InitiativeRow.case_id == InitiativeRevisionRow.case_id)
                    & (InitiativeRow.current_revision == InitiativeRevisionRow.revision),
                )
                .where(
                    InitiativeRevisionRow.poll_id == poll_id,
                    InitiativeRevisionRow.house_id == house_id,
                )
            )
            if revision is None:
                raise InitiativeConflict("initiative revision is no longer current")
            answered = {answer.resident_id for answer in poll.answers}
            safe_ids = tuple(
                resident_id
                for resident_id in sorted(set(candidate_ids), key=lambda item: item.bytes)
                if resident_id in poll.definition.eligible_residents and resident_id not in answered
            )
            reachable = await _currently_reachable(session, house_id, safe_ids, now)
            planned: list[UUID] = []
            for resident_id in reachable:
                last = await session.scalar(
                    select(InitiativeReminderRow)
                    .where(
                        InitiativeReminderRow.poll_id == poll_id,
                        InitiativeReminderRow.resident_id == resident_id,
                    )
                    .order_by(InitiativeReminderRow.number.desc())
                    .limit(1)
                )
                number = 1 if last is None else last.number + 1
                if number > policy.max_per_resident:
                    continue
                if last is not None and now - last.queued_at < policy.min_interval:
                    continue
                outbox_id = await PostgresDeliveryQueue(session, self.clock).enqueue(
                    DeliveryIntent(
                        house_id=house_id,
                        operation_key=f"initiative:reminder:{poll_id}:{resident_id}:{number}",
                        text=(
                            f"Напоминание: демо-опрос по инициативе «{revision.wording[:2000]}» "
                            f"открыт до {poll.definition.closes_at.isoformat()}. "
                            "Если ещё не отвечали, проверьте сообщение с опросом."
                        ),
                        recipient_id=resident_id,
                    )
                )
                session.add(
                    InitiativeReminderRow(
                        id=uuid4(),
                        poll_id=poll_id,
                        house_id=house_id,
                        resident_id=resident_id,
                        number=number,
                        queued_at=now,
                        outbox_id=outbox_id,
                    )
                )
                planned.append(resident_id)
            session.add(
                InitiativeReminderBatchRow(
                    id=uuid4(),
                    poll_id=poll_id,
                    house_id=house_id,
                    operation_key=operation_key,
                    targets=[str(resident_id) for resident_id in planned],
                    created_at=now,
                )
            )
            await session.flush()
            return tuple(planned)

    async def save_decision_once(
        self, decision: InitiativeDecision, operation_key: str
    ) -> InitiativeDecision:
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid decision operation key")
        async with self.sessions.begin() as session:
            poll_row = await session.scalar(
                select(PollRow)
                .where(PollRow.id == decision.poll_id, PollRow.house_id == decision.house_id)
                .with_for_update()
            )
            if poll_row is None:
                raise InitiativeConflict("initiative poll is missing")
            prior = await session.scalar(
                select(InitiativeDecisionRow).where(
                    InitiativeDecisionRow.house_id == decision.house_id,
                    InitiativeDecisionRow.operation_key == operation_key,
                )
            )
            if prior is not None:
                if prior.poll_id != decision.poll_id or prior.outcome != decision.outcome.value:
                    raise InitiativeConflict("decision operation key conflict")
                return self._to_decision(prior)
            poll = await PostgresPollRepository(session).get_state(
                decision.poll_id, decision.house_id
            )
            if (
                poll is None
                or poll.status != PollStatus.CLOSED
                or poll.version != decision.poll_version
                or poll.definition.case_id != decision.case_id
                or poll.outcome != decision.outcome
            ):
                raise InitiativeConflict("poll changed before decision commit")
            initiative = await session.scalar(
                select(InitiativeRow).where(
                    InitiativeRow.case_id == decision.case_id,
                    InitiativeRow.house_id == decision.house_id,
                )
            )
            if initiative is None or initiative.current_revision != decision.initiative_revision:
                raise InitiativeConflict("initiative changed before decision commit")
            existing = await session.get(InitiativeDecisionRow, decision.poll_id)
            if existing is not None:
                if existing.outcome != decision.outcome.value:
                    raise InitiativeConflict("initiative decision changed")
                return self._to_decision(existing)
            session.add(
                InitiativeDecisionRow(
                    poll_id=decision.poll_id,
                    house_id=decision.house_id,
                    case_id=decision.case_id,
                    initiative_revision=decision.initiative_revision,
                    poll_version=decision.poll_version,
                    outcome=decision.outcome.value,
                    decided_at=decision.decided_at,
                    policy_revision=decision.policy_revision,
                    demo=decision.demo,
                    operation_key=operation_key,
                )
            )
            chat_id = await session.scalar(
                select(HouseRow.max_chat_id).where(HouseRow.id == decision.house_id)
            )
            if chat_id is not None and chat_id.isdecimal():
                label = (
                    "поддержана по демонстрационному правилу"
                    if decision.outcome == InitiativeOutcome.SUPPORTED
                    else "не получила достаточной поддержки по демонстрационному правилу"
                )
                await PostgresDeliveryQueue(session, self.clock).enqueue(
                    DeliveryIntent(
                        house_id=decision.house_id,
                        operation_key=f"initiative:decision:{decision.poll_id}",
                        text=f"Позиция жителей по инициативе {label}. Это не протокол ОСС.",
                        chat_id=chat_id,
                    )
                )
            await session.flush()
            return decision

    @staticmethod
    def _to_decision(row: InitiativeDecisionRow) -> InitiativeDecision:
        return InitiativeDecision(
            case_id=row.case_id,
            house_id=row.house_id,
            initiative_revision=row.initiative_revision,
            poll_id=row.poll_id,
            poll_version=row.poll_version,
            outcome=InitiativeOutcome(row.outcome),
            decided_at=row.decided_at,
            policy_revision=row.policy_revision,
            demo=row.demo,
        )
