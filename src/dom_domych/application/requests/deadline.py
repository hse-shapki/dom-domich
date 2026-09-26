"""K12: проверка зарегистрированного обращения при наступлении срока."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.jobs import DueJob
from dom_domych.infrastructure.postgres.request_models import RequestRow


class RequestDeadlineRevisionReader:
    """RevisionRouter читает текущее состояние; handler повторяет проверку под lock."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def current_version(self, job: DueJob) -> int | None:
        if job.event_name is not EventName.REQUEST_DEADLINE_REACHED:
            return None
        async with self.sessions() as session:
            row = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == job.entity_id,
                    RequestRow.house_id == job.house_id,
                    RequestRow.status == "registered",
                )
            )
            if row is None:
                return None
            case = await session.scalar(
                select(CaseRow).where(
                    CaseRow.id == row.case_id,
                    CaseRow.house_id == job.house_id,
                    CaseRow.status == "in_progress",
                )
            )
            return case.version if case is not None else None


class RequestDeadlineHandler:
    """Создаёт проверяемый черновик followup без заявления о его отправке."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.name is not EventName.REQUEST_DEADLINE_REACHED:
            return False
        if (
            event.source is not EventSource.SCHEDULER
            or event.house_id is None
            or event.entity is None
        ):
            raise ValueError("UNTRUSTED_DEADLINE_EVENT")
        if self.clock.now() < event.occurred_at:
            raise ValueError("DEADLINE_NOT_DUE")
        await self._prepare(
            event.house_id,
            event.entity.entity_id,
            event.entity.entity_version,
            event.event_id,
        )
        return True

    async def _prepare(
        self, house_id: UUID, request_id: UUID, expected_version: int, event_id: UUID
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == request_id, RequestRow.house_id == house_id
                )
            )
            if row is None or row.status != "registered" or row.registered_at is None:
                return
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == row.case_id, CaseRow.house_id == house_id)
                .with_for_update()
            )
            if (
                case is None
                or case.version != expected_version
                or case.status != "in_progress"
                or case.closed_at is not None
            ):
                return
            before = case.version
            case.version += 1
            case.status = "followup_draft"
            session.add(
                CaseEventRow(
                    id=uuid4(),
                    case_id=case.id,
                    house_id=house_id,
                    event_type=EventName.REQUEST_DEADLINE_REACHED.value,
                    before_version=before,
                    after_version=case.version,
                    actor_id=None,
                    source_message_id=None,
                    operation_id=event_id,
                    occurred_at=self.clock.now(),
                    facts={
                        "request_id": str(request_id),
                        "registration_id": row.registration_id,
                        "registered_at": row.registered_at.isoformat(),
                        "rule_id": str(row.rule_id),
                        "source_refs": row.source_refs,
                        "draft_kind": "followup",
                        "draft_status": "needs_review",
                        "draft_text": (
                            f"По обращению {row.registration_id} просим сообщить текущий статус "
                            "и подтверждённые действия по устранению проблемы."
                        ),
                    },
                )
            )
