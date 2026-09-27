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
from dom_domych.domain.polls.models import PollKind
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.case_models import CaseRow
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.polls import PostgresPollRepository
from dom_domych.infrastructure.postgres.request_models import RequestRow
from dom_domych.infrastructure.postgres.z_audience_models import AudienceSnapshotRow
from dom_domych.infrastructure.postgres.z_poll_models import PollRow


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
        async with self.sessions() as session:
            request = await session.scalar(
                select(RequestRow).where(
                    RequestRow.id == event.entity.entity_id,
                    RequestRow.house_id == event.house_id,
                    RequestRow.case_id == event.entity.case_id,
                )
            )
            case = await session.scalar(
                select(CaseRow).where(
                    CaseRow.id == event.entity.case_id,
                    CaseRow.house_id == event.house_id,
                )
            )
            house = await session.get(HouseRow, event.house_id)
            origin = await session.scalar(
                select(PollRow)
                .where(
                    PollRow.case_id == event.entity.case_id,
                    PollRow.house_id == event.house_id,
                    PollRow.kind.in_(
                        (
                            PollKind.PROBLEM_CONFIRMATION.value,
                            PollKind.INITIATIVE_POSITION.value,
                        )
                    ),
                )
                .order_by(PollRow.opens_at, PollRow.id)
                .limit(1)
            )
            if (
                request is None
                or request.status != "registered"
                or request.approval_actor is None
                or request.registration_id is None
                or request.executor_operation_id is None
                or not request.source_refs
                or case is None
                or house is None
                or origin is None
            ):
                return False
            audience = await session.scalar(
                select(AudienceSnapshotRow).where(
                    AudienceSnapshotRow.id == origin.audience_id,
                    AudienceSnapshotRow.house_id == event.house_id,
                )
            )
            poll = await PostgresPollRepository(session).get_state(origin.id, event.house_id)
            if audience is None or poll is None:
                return False
            location = self._location(case)
            case_ref = f"case:{case.id}:v{case.version}"
            rule_ref = request.source_refs[0]
            facts = [
                DocumentFact("Тема", case.title, case_ref),
                DocumentFact("Описание", case.description, case_ref),
                DocumentFact("Ответственный", str(request.responsible_id), rule_ref),
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
                poll_id=poll.definition.poll_id,
                poll_revision=poll.version,
                policy_revision=poll.definition.policy.revision,
                request_id=request.id,
                request_revision=request.draft_version,
                title=f"Обращение: {case.title}",
                house_address=house.address,
                facts=tuple(facts),
                tally=poll.tally,
                notices=(),
                created_at=self.clock.now(),
            )
            recipient_id = request.approval_actor
        await PostgresDocuments(self.sessions).prepare(
            snapshot,
            recipient_id,
            operation_key=f"request:appeal:{request.id}:v{request.draft_version}",
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
