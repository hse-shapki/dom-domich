"""Проверка результата в одной UoW с poll, case, jobs и outbox."""

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.polls.callback import StoredPollAction
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.domain.polls.models import PollKind, PollState, PollStatus, VoteChoice
from dom_domych.domain.ports.core import Clock, DeliveryIntent
from dom_domych.domain.resolution.models import (
    ResolutionConflict,
    ResolutionState,
    ResolutionStatus,
)
from dom_domych.infrastructure.postgres.audiences import PostgresAudienceRepository
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.delivery import PostgresDeliveryQueue
from dom_domych.infrastructure.postgres.inbox import save_domain_event
from dom_domych.infrastructure.postgres.models import HouseRow, ScheduledJobRow
from dom_domych.infrastructure.postgres.poll_actions import PostgresPollActionStore
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.z_executor_models import DemoExecutorRow
from dom_domych.infrastructure.postgres.z_poll_models import PollRow
from dom_domych.infrastructure.postgres.z_resolution_models import ResolutionCheckRow


@dataclass(frozen=True)
class ResolutionCaseView:
    case_id: UUID
    house_id: UUID
    request_id: UUID
    original_audience_id: UUID
    version: int
    workflow_status: str


def _state(row: ResolutionCheckRow) -> ResolutionState:
    return ResolutionState(
        check_id=row.id,
        case_id=row.case_id,
        house_id=row.house_id,
        request_id=row.request_id,
        original_audience_id=row.original_audience_id,
        poll_id=row.poll_id,
        case_version_at_start=row.case_version_at_start,
        done_event_id=row.done_event_id,
        started_at=row.started_at,
        status=ResolutionStatus(row.status),
        poll_version_at_decision=row.poll_version_at_decision,
        decided_at=row.decided_at,
        version=row.version,
    )


class PostgresResolutionCasePort:
    """Исходная аудитория берётся из первого опроса дела, а не из новой категории."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_for_resolution(self, case_id: UUID, house_id: UUID) -> ResolutionCaseView:
        async with self.sessions() as session:
            case = await session.scalar(
                select(CaseRow).where(CaseRow.id == case_id, CaseRow.house_id == house_id)
            )
            request = await session.scalar(
                select(RequestRow)
                .where(RequestRow.case_id == case_id, RequestRow.house_id == house_id)
                .order_by(RequestRow.id)
                .limit(1)
            )
            origin = await session.scalar(
                select(PollRow)
                .where(
                    PollRow.case_id == case_id,
                    PollRow.house_id == house_id,
                    PollRow.kind.in_(
                        (PollKind.PROBLEM_CONFIRMATION.value, PollKind.INITIATIVE_POSITION.value)
                    ),
                )
                .order_by(PollRow.opens_at, PollRow.id)
                .limit(1)
            )
            if case is None or request is None or origin is None:
                raise ResolutionConflict("case, request or original audience is unavailable")
            return ResolutionCaseView(
                case.id, house_id, request.id, origin.audience_id, case.version, case.status
            )


class PostgresResolutionStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def start_once(
        self,
        state: ResolutionState,
        poll: PollState,
        notification_targets: tuple[UUID, ...],
        operation_key: str,
    ) -> ResolutionState:
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid resolution operation key")
        async with self.sessions.begin() as session:
            prior = await session.scalar(
                select(ResolutionCheckRow).where(
                    ResolutionCheckRow.house_id == state.house_id,
                    (ResolutionCheckRow.start_operation_key == operation_key)
                    | (ResolutionCheckRow.done_event_id == state.done_event_id),
                )
            )
            if prior is not None:
                if (
                    prior.case_id != state.case_id
                    or prior.request_id != state.request_id
                    or prior.original_audience_id != state.original_audience_id
                    or (
                        prior.start_operation_key == operation_key
                        and prior.done_event_id != state.done_event_id
                    )
                ):
                    raise ResolutionConflict("start operation key was reused")
                return _state(prior)
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == state.case_id, CaseRow.house_id == state.house_id)
                .with_for_update()
            )
            request = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == state.request_id,
                    RequestRow.case_id == state.case_id,
                    RequestRow.house_id == state.house_id,
                )
            )
            origin = await session.scalar(
                select(PollRow)
                .where(
                    PollRow.case_id == state.case_id,
                    PollRow.house_id == state.house_id,
                    PollRow.kind.in_(
                        (PollKind.PROBLEM_CONFIRMATION.value, PollKind.INITIATIVE_POSITION.value)
                    ),
                )
                .order_by(PollRow.opens_at, PollRow.id)
                .limit(1)
            )
            external = await session.scalar(
                select(DemoExecutorRow).where(
                    DemoExecutorRow.request_id == state.request_id,
                    DemoExecutorRow.house_id == state.house_id,
                )
            )
            audience = await PostgresAudienceRepository(session).get_scoped(
                state.original_audience_id, state.house_id
            )
            if (
                case is None
                or case.version != state.case_version_at_start
                or case.status != "in_progress"
                or request is None
                or origin is None
                or origin.audience_id != state.original_audience_id
                or external is None
                or external.status != "done"
                or str(state.done_event_id) not in external.processed_event_ids
                or audience is None
                or frozenset(item.resident_id for item in audience.members)
                != poll.definition.eligible_residents
                or poll.definition.case_id != state.case_id
                or poll.definition.audience_id != state.original_audience_id
                or poll.definition.subject_revision != case.version
            ):
                raise ResolutionConflict("case, done event or original audience changed")
            await PostgresPollRepository(session).open_once(
                poll, notification_targets, f"resolution:poll:{state.done_event_id}"
            )
            session.add(
                ResolutionCheckRow(
                    id=state.check_id,
                    house_id=state.house_id,
                    case_id=state.case_id,
                    request_id=state.request_id,
                    original_audience_id=state.original_audience_id,
                    poll_id=state.poll_id,
                    case_version_at_start=state.case_version_at_start,
                    done_event_id=state.done_event_id,
                    start_operation_key=operation_key,
                    started_at=state.started_at,
                    status=ResolutionStatus.CHECKING.value,
                    version=state.version,
                )
            )
            case.status = "checking_resolution"
            case.version += 1
            self._case_event(
                session,
                case,
                "resolution.started",
                state.check_id,
                state.started_at,
                {"poll_id": str(state.poll_id), "done_event_id": str(state.done_event_id)},
            )
            for resident_id in notification_targets:
                actions = PostgresPollActionStore(session)
                yes_token = await actions.create(
                    StoredPollAction(
                        poll_id=state.poll_id,
                        house_id=state.house_id,
                        audience_id=state.original_audience_id,
                        subject_revision=state.case_version_at_start,
                        choice=VoteChoice.YES,
                        expires_at=poll.definition.closes_at,
                        bound_resident_id=resident_id,
                    )
                )
                no_token = await actions.create(
                    StoredPollAction(
                        poll_id=state.poll_id,
                        house_id=state.house_id,
                        audience_id=state.original_audience_id,
                        subject_revision=state.case_version_at_start,
                        choice=VoteChoice.NO,
                        expires_at=poll.definition.closes_at,
                        bound_resident_id=resident_id,
                    )
                )
                await PostgresDeliveryQueue(session, self.clock).enqueue(
                    DeliveryIntent(
                        house_id=state.house_id,
                        operation_key=f"resolution:check:{state.poll_id}:{resident_id}",
                        text=(
                            "Демо-исполнитель отметил выполнение. "
                            "Подтвердите фактический результат в опросе дома."
                        ),
                        recipient_id=resident_id,
                        buttons=(("Подтверждаю", yes_token), ("Не подтверждаю", no_token)),
                    )
                )
            return state

    async def finalize_atomic(
        self,
        check_id: UUID,
        house_id: UUID,
        poll: PollState,
        at: datetime,
        operation_key: str,
    ) -> ResolutionState:
        if not operation_key or len(operation_key) > 250:
            raise ValueError("invalid resolution finalization key")
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(ResolutionCheckRow)
                .where(ResolutionCheckRow.id == check_id, ResolutionCheckRow.house_id == house_id)
                .with_for_update()
            )
            if row is None:
                raise ResolutionConflict("check not found in this house")
            current = _state(row)
            if current.status is not ResolutionStatus.CHECKING:
                if (
                    row.finalize_operation_key == operation_key
                    or row.poll_id == poll.definition.poll_id
                ):
                    return current
                raise ResolutionConflict("finalization key was reused")
            if poll.status is not PollStatus.CLOSED or poll.definition.poll_id != row.poll_id:
                raise ResolutionConflict("poll is not finalized for this check")
            persisted = await PostgresPollRepository(session).get_state(row.poll_id, house_id)
            if persisted != poll:
                raise ResolutionConflict("poll changed before resolution decision")
            updated = current.decide(poll, at)
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == row.case_id, CaseRow.house_id == house_id)
                .with_for_update()
            )
            if (
                case is None
                or case.status != "checking_resolution"
                or case.version != row.case_version_at_start + 1
            ):
                raise ResolutionConflict("case changed before resolution decision")
            row.status = updated.status.value
            row.poll_version_at_decision = updated.poll_version_at_decision
            row.decided_at = updated.decided_at
            row.finalize_operation_key = operation_key
            row.version = updated.version
            case.status = updated.status.value
            case.version += 1
            if updated.status is ResolutionStatus.CLOSED:
                case.closed_at = at
            event_type = {
                ResolutionStatus.CLOSED: "resolution.confirmed",
                ResolutionStatus.REOPENED: "resolution.rejected",
                ResolutionStatus.UNCONFIRMED: "resolution.unconfirmed",
            }[updated.status]
            self._case_event(
                session,
                case,
                event_type,
                uuid5(NAMESPACE_URL, f"resolution:final:{check_id}"),
                at,
                {"poll_id": str(row.poll_id), "outcome": updated.status.value},
            )
            await session.execute(
                update(ScheduledJobRow)
                .where(
                    ScheduledJobRow.house_id == house_id,
                    ScheduledJobRow.status == "pending",
                    ScheduledJobRow.entity_id.in_((row.poll_id, row.case_id, row.request_id)),
                )
                .values(status="skipped_stale", error_code="resolution_decided")
            )
            house = await session.get(HouseRow, house_id)
            if house is not None and house.max_chat_id is not None:
                text = {
                    ResolutionStatus.CLOSED: "Жители подтвердили результат; дело закрыто.",
                    ResolutionStatus.REOPENED: "Жители не подтвердили результат; дело возвращено.",
                    ResolutionStatus.UNCONFIRMED: (
                        "Ответов для подтверждения результата недостаточно; дело остаётся открытым."
                    ),
                }[updated.status]
                await PostgresDeliveryQueue(session, self.clock).enqueue(
                    DeliveryIntent(
                        house_id=house_id,
                        operation_key=f"resolution:outcome:{check_id}",
                        text=f"{text} Правило проверки: демо.",
                        chat_id=house.max_chat_id,
                    )
                )
            if updated.status is ResolutionStatus.REOPENED:
                await save_domain_event(
                    session,
                    EventEnvelope(
                        event_id=uuid4(),
                        source=EventSource.DOMAIN,
                        source_key=f"resolution:rejected:{check_id}",
                        name=EventName.RESOLUTION_REJECTED,
                        occurred_at=at,
                        received_at=at,
                        correlation_id=check_id,
                        house_id=house_id,
                        entity=EntityEventPayload(
                            entity_id=check_id,
                            entity_version=updated.version,
                            case_id=row.case_id,
                            causation_id=row.poll_id,
                        ),
                    ),
                )
            return updated

    @staticmethod
    def _case_event(
        session: AsyncSession,
        case: CaseRow,
        event_type: str,
        operation_id: UUID,
        at: datetime,
        facts: dict[str, object],
    ) -> None:
        session.add(
            CaseEventRow(
                id=uuid4(),
                case_id=case.id,
                house_id=case.house_id,
                event_type=event_type,
                before_version=case.version - 1,
                after_version=case.version,
                actor_id=None,
                source_message_id=None,
                operation_id=operation_id,
                occurred_at=at,
                facts=facts,
            )
        )
