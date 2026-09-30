"""Подготовка документов из сохранённых фактов; рендер читает только snapshot."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EventName
from dom_domych.domain.documents.snapshot import (
    DocumentFact,
    DocumentKind,
    DocumentMode,
    DocumentSnapshot,
    NoticeEntry,
    NoticeStatus,
)
from dom_domych.domain.polls.models import PollStatus
from dom_domych.domain.ports.core import Clock, DocumentRef
from dom_domych.infrastructure.postgres.case_models import CaseEventRow, CaseRow
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
from dom_domych.infrastructure.postgres.knowledge_models import (
    KnowledgeSourceRow,
    RuleVersionRow,
)
from dom_domych.infrastructure.postgres.models import HouseRow, OutboxDeliveryRow
from dom_domych.infrastructure.postgres.original_audience import original_audience_id, original_poll
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow
from dom_domych.infrastructure.postgres.z_followup_models import InitiativeDecisionRow
from dom_domych.infrastructure.postgres.z_initiative_models import (
    InitiativeRevisionRow,
    InitiativeRow,
)


class DocumentContext(Protocol):
    @property
    def house_id(self) -> UUID: ...

    @property
    def actor_id(self) -> UUID | None: ...

    @property
    def capabilities(self) -> frozenset[str]: ...


@dataclass(frozen=True)
class PositionWorkerContext:
    house_id: UUID
    actor_id: UUID
    capabilities: frozenset[str] = frozenset({"document.prepare"})


_TEMPLATES = {
    DocumentKind.RESIDENT_POSITION: "resident-position-v1",
    DocumentKind.NOTIFICATION_REGISTER: "notification-register-v1",
    DocumentKind.COMPLAINT_DRAFT: "complaint-draft-v1",
}
_TITLES = {
    DocumentKind.RESIDENT_POSITION: "Позиция жителей",
    DocumentKind.NOTIFICATION_REGISTER: "Приватный реестр уведомлений",
    DocumentKind.COMPLAINT_DRAFT: "Черновик жалобы — требуется проверка",
}


class CaseDocumentPreparer:
    """Приватный реестр требует отдельного trusted права, не выводится в общий чат."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def prepare(
        self, kind: DocumentKind, case_id: UUID, context: DocumentContext, *, operation_key: str
    ) -> DocumentRef:
        if context.actor_id is None or "document.prepare" not in context.capabilities:
            raise PermissionError("DOCUMENT_PREPARATION_FORBIDDEN")
        if kind is DocumentKind.NOTIFICATION_REGISTER:
            if "document.notice_register" not in context.capabilities:
                raise PermissionError("NOTICE_REGISTER_FORBIDDEN")
        if kind not in _TEMPLATES:
            raise ValueError("appeal is prepared by trusted registration")
        async with self.sessions.begin() as session:
            case = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == case_id, CaseRow.house_id == context.house_id)
                .with_for_update()
            )
            if case is None:
                raise ValueError("CASE_NOT_FOUND")
            existing = await session.scalar(
                select(DocumentRow).where(
                    DocumentRow.house_id == context.house_id,
                    DocumentRow.operation_key == operation_key,
                )
            )
            if existing is not None:
                if (
                    existing.case_id != case_id
                    or existing.kind != kind.value
                    or existing.recipient_id != context.actor_id
                ):
                    raise ValueError("document operation key conflicts with other contents")
                return PostgresDocuments._ref(existing)
            house = await session.get(HouseRow, context.house_id)
            origin = await original_poll(session, case)
            audience_id = await original_audience_id(session, case)
            audience = await session.get(AudienceSnapshotRow, audience_id) if audience_id else None
            if house is None or audience is None:
                raise ValueError("document original audience is missing")
            poll = (
                await PostgresPollRepository(session).get_state(origin.id, context.house_id)
                if origin
                else None
            )
            facts: list[DocumentFact] = [
                DocumentFact("Тема", case.title, f"case:{case.id}:v{case.version}"),
                DocumentFact("Описание", case.description, f"case:{case.id}:v{case.version}"),
            ]
            request: RequestRow | None = None
            if kind is DocumentKind.RESIDENT_POSITION:
                initiative = await session.get(InitiativeRow, case.id)
                decision = await session.get(InitiativeDecisionRow, origin.id) if origin else None
                if (
                    initiative is None
                    or initiative.author_id != context.actor_id
                    or decision is None
                    or poll is None
                    or origin is None
                    or poll.status is not PollStatus.CLOSED
                ):
                    raise ValueError("final initiative position is unavailable for this recipient")
                revision = await session.get(
                    InitiativeRevisionRow, (case.id, initiative.current_revision)
                )
                if revision is None or revision.poll_id != origin.id:
                    raise ValueError("initiative revision changed")
                facts[1] = DocumentFact(
                    "Формулировка", revision.wording, f"initiative:{case.id}:v{revision.revision}"
                )
                facts.append(
                    DocumentFact(
                        "Итог",
                        (
                            "Поддержана по демо-правилу"
                            if decision.outcome == "supported"
                            else "Недостаточно поддержки по демо-правилу"
                        ),
                        f"poll:{decision.poll_id}:v{decision.poll_version}",
                    )
                )
            if kind is DocumentKind.COMPLAINT_DRAFT:
                deadline = await session.scalar(
                    select(CaseEventRow)
                    .where(
                        CaseEventRow.case_id == case.id,
                        CaseEventRow.house_id == context.house_id,
                        CaseEventRow.event_type == EventName.REQUEST_DEADLINE_REACHED.value,
                    )
                    .order_by(CaseEventRow.occurred_at.desc(), CaseEventRow.id.desc())
                    .limit(1)
                )
                if deadline is None or case.status != "followup_draft":
                    raise ValueError("verified followup draft is missing")
                request = await session.scalar(
                    select(RequestRow).where(
                        RequestRow.case_id == case.id,
                        RequestRow.house_id == context.house_id,
                        RequestRow.id == UUID(str(deadline.facts["request_id"])),
                        RequestRow.status == "registered",
                        RequestRow.approval_actor == context.actor_id,
                    )
                )
                if (
                    request is None
                    or not request.source_refs
                    or deadline.facts.get("draft_status") != "needs_review"
                ):
                    raise ValueError("registered request or reviewed source is missing")
                rule = await session.get(RuleVersionRow, request.rule_id)
                source = (
                    await session.get(KnowledgeSourceRow, (rule.source_id, rule.source_revision))
                    if rule is not None
                    else None
                )
                facts.extend(
                    (
                        DocumentFact(
                            "Черновик",
                            str(deadline.facts["draft_text"]),
                            f"case_event:{deadline.id}",
                        ),
                        DocumentFact(
                            "Источник правила",
                            source.title if source is not None else "Проверенный документ дома",
                            request.source_refs[0],
                        ),
                        DocumentFact(
                            "Регистрация",
                            request.registration_id or "не указана",
                            f"request:{request.id}:v{request.draft_version}",
                        ),
                        DocumentFact(
                            "Статус",
                            "Требуется проверка человеком. Документ не отправлен исполнителю.",
                            f"case_event:{deadline.id}",
                        ),
                    )
                )
            notices: tuple[NoticeEntry, ...] = ()
            if kind is DocumentKind.NOTIFICATION_REGISTER:
                if poll is None:
                    raise ValueError("notice register needs an original poll")
                rows = (
                    await session.scalars(
                        select(OutboxDeliveryRow).where(
                            OutboxDeliveryRow.house_id == context.house_id,
                            OutboxDeliveryRow.operation_key.like(
                                f"poll:invite:{poll.definition.poll_id}:%"
                            ),
                        )
                    )
                ).all()
                by_resident = {row.recipient_id: row for row in rows}
                notices = tuple(
                    NoticeEntry(
                        resident_id,
                        NoticeStatus(by_resident[resident_id].status)
                        if resident_id in by_resident
                        and by_resident[resident_id].status in {item.value for item in NoticeStatus}
                        else NoticeStatus.PENDING,
                        None,  # Время попытки отсутствует в outbox; planned time не выдаём за него.
                        by_resident[resident_id].id if resident_id in by_resident else None,
                    )
                    for resident_id in sorted(poll.definition.eligible_residents)
                )
                facts.append(
                    DocumentFact(
                        "Назначение",
                        (
                            "Для уполномоченного адресата. Ожидание отправки не означает доставку; "
                            "время попыток не зафиксировано."
                        ),
                        f"poll:{poll.definition.poll_id}",
                    )
                )
            snapshot = DocumentSnapshot(
                kind=kind,
                mode=DocumentMode.DEMO if house.demo else DocumentMode.LIVE_DRAFT,
                template_revision=_TEMPLATES[kind],
                house_id=house.id,
                case_id=case.id,
                case_revision=case.version,
                audience_id=audience.id,
                audience_revision=audience.criteria_revision,
                poll_id=poll.definition.poll_id if poll else None,
                poll_revision=poll.version if poll else None,
                policy_revision=poll.definition.policy.revision if poll else None,
                request_id=request.id if request else None,
                request_revision=request.draft_version if request else None,
                title=f"{_TITLES[kind]}: {case.title}",
                house_address=house.address,
                facts=tuple(facts),
                tally=poll.tally if poll else None,
                notices=notices,
                created_at=self.clock.now(),
            )
            return await PostgresDocuments(self.sessions).prepare_in_session(
                session, snapshot, context.actor_id, operation_key=operation_key
            )
