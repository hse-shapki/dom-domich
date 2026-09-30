"""Production-снимок обращения из доверенного события регистрации."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.documents.snapshot import (
    DocumentFact,
    DocumentKind,
    DocumentMode,
    DocumentSnapshot,
)
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
from dom_domych.infrastructure.postgres.knowledge_models import RuleVersionRow
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.original_audience import original_audience_id, original_poll
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_document_models import DocumentRow


class RequestDocumentEventHandler:
    """Ставит appeal PDF в очередь, не перечитывая факты во время рендера."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self.sessions = sessions
        self.clock = clock

    async def __call__(self, event: EventEnvelope) -> bool:
        if (
            event.name is not EventName.REQUEST_REGISTERED
            or event.source is not EventSource.DOMAIN
            or event.house_id is None
            or event.entity is None
            or event.entity.case_id is None
        ):
            return False
        async with self.sessions.begin() as session:
            request = await session.scalar(
                select(RequestRow)
                .where(
                    RequestRow.id == event.entity.entity_id,
                    RequestRow.house_id == event.house_id,
                    RequestRow.case_id == event.entity.case_id,
                )
                .with_for_update()
            )
            if request is None:
                return False
            operation_key = f"request:appeal:{request.id}:v{request.draft_version}"
            # Повтор события возвращает уже зафиксированные факты, даже если дело изменилось.
            existing = await session.scalar(
                select(DocumentRow.id).where(
                    DocumentRow.house_id == event.house_id,
                    DocumentRow.operation_key == operation_key,
                )
            )
            if existing is not None:
                return False
            case = await session.scalar(
                select(CaseRow).where(
                    CaseRow.id == event.entity.case_id,
                    CaseRow.house_id == event.house_id,
                )
            )
            house = await session.get(HouseRow, event.house_id)
            if (
                request is None
                or request.status != "registered"
                or request.approval_actor is None
                or request.registration_id is None
                or request.executor_operation_id is None
                or not request.source_refs
                or case is None
                or house is None
            ):
                return False
            origin = await original_poll(session, case)
            audience_id = await original_audience_id(session, case)
            if audience_id is None:
                return False
            audience = await session.scalar(
                select(AudienceSnapshotRow).where(
                    AudienceSnapshotRow.id == audience_id,
                    AudienceSnapshotRow.house_id == event.house_id,
                )
            )
            poll = (
                await PostgresPollRepository(session).get_state(origin.id, event.house_id)
                if origin is not None
                else None
            )
            if audience is None:
                return False
            location = self._location(case)
            case_ref = f"case:{case.id}:v{case.version}"
            rule_ref = request.source_refs[0]
            rule = await session.get(RuleVersionRow, request.rule_id)
            responsible_name = (
                rule.responsible_name
                if rule is not None and rule.responsible_id == request.responsible_id
                else None
            )
            facts = [
                DocumentFact("Тема", case.title, case_ref),
                DocumentFact("Описание", case.description, case_ref),
                DocumentFact(
                    "Ответственная служба",
                    responsible_name or "Название не указано в проверенном правиле",
                    rule_ref,
                ),
                DocumentFact(
                    "Регистрация demo executor",
                    request.registration_id,
                    f"demo_executor:{request.executor_operation_id}",
                ),
            ]
            if location:
                facts.insert(2, DocumentFact("Место", location, case_ref))
            snapshot = DocumentSnapshot(
                kind=DocumentKind.APPEAL,
                mode=DocumentMode.DEMO if house.demo else DocumentMode.LIVE_DRAFT,
                template_revision="appeal-v1",
                house_id=house.id,
                case_id=case.id,
                case_revision=case.version,
                audience_id=audience.id,
                audience_revision=audience.criteria_revision,
                poll_id=poll.definition.poll_id if poll is not None else None,
                poll_revision=poll.version if poll is not None else None,
                policy_revision=poll.definition.policy.revision if poll is not None else None,
                request_id=request.id,
                request_revision=request.draft_version,
                title=f"Обращение: {case.title}",
                house_address=house.address,
                facts=tuple(facts),
                tally=poll.tally if poll is not None else None,
                notices=(),
                created_at=request.registered_at or event.occurred_at,
            )
            recipient_id = request.approval_actor
            await PostgresDocuments(self.sessions).prepare_in_session(
                session, snapshot, recipient_id, operation_key=operation_key
            )
        # Следующий handler запускает continuation уже после постановки документа в очередь.
        return False

    @staticmethod
    def _location(case: CaseRow) -> str:
        parts: list[str] = []
        if case.entrance is not None:
            parts.append(f"подъезд {case.entrance}")
        if case.floor is not None:
            parts.append(f"этаж {case.floor}")
        if case.object_name:
            parts.append(case.object_name)
        return ", ".join(parts)
