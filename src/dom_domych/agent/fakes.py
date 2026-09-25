"""Изолированные fake ports для проверки стыка K00 до общей persistence."""

from __future__ import annotations

from uuid import UUID, uuid4

from dom_domych.agent.contracts import (
    CaseAttachMessage,
    CaseCandidate,
    CaseCreate,
    CaseSearch,
    CaseView,
    KnowledgeHit,
    KnowledgeSearch,
    RequestPrepare,
    RequestSubmit,
    RequestView,
    TrustedContext,
)


class FakeCasePort:
    def __init__(self) -> None:
        self.cases: dict[UUID, tuple[UUID, CaseView]] = {}
        self.messages: set[tuple[UUID, UUID]] = set()
        self.operations: dict[tuple[UUID, UUID], CaseView] = {}

    async def search(
        self, command: CaseSearch, context: TrustedContext
    ) -> tuple[CaseCandidate, ...]:
        return tuple(
            CaseCandidate(
                case_id=case.case_id,
                version=case.version,
                kind=case.kind,
                title=case.title,
                entrance=None,
                floor=None,
                object_name=None,
                source_refs=case.source_refs,
            )
            for house_id, case in self.cases.values()
            if house_id == context.house_id and command.query.casefold() in case.title.casefold()
        )

    async def get(self, case_id: UUID, context: TrustedContext) -> CaseView | None:
        item = self.cases.get(case_id)
        return item[1] if item is not None and item[0] == context.house_id else None

    async def create(self, command: CaseCreate, context: TrustedContext) -> CaseView:
        key = (context.house_id, command.operation_id)
        prior = self.operations.get(key)
        if prior is not None:
            return prior
        case = CaseView(
            case_id=uuid4(),
            version=1,
            kind=command.kind,
            title=command.title,
            status="detected",
            source_refs=(f"message:{command.source_message_id}",),
        )
        self.cases[case.case_id] = (context.house_id, case)
        self.operations[key] = case
        return case

    async def attach_message(self, command: CaseAttachMessage, context: TrustedContext) -> CaseView:
        key = (context.house_id, command.operation_id)
        prior = self.operations.get(key)
        if prior is not None:
            return prior
        case = await self.get(command.case_id, context)
        if case is None:
            raise ValueError("CASE_NOT_FOUND")
        if case.version != command.expected_version:
            raise ValueError("VERSION_CONFLICT")
        link = (case.case_id, command.message_id)
        if link in self.messages:
            raise ValueError("MESSAGE_ALREADY_ATTACHED")
        self.messages.add(link)
        updated = case.model_copy(
            update={
                "version": case.version + 1,
                "source_refs": (*case.source_refs, f"message:{command.message_id}"),
            }
        )
        self.cases[case.case_id] = (context.house_id, updated)
        self.operations[key] = updated
        return updated


class FakeKnowledgePort:
    def __init__(self, hits: tuple[tuple[UUID | None, KnowledgeHit], ...] = ()) -> None:
        self.hits = hits

    async def search(
        self, command: KnowledgeSearch, context: TrustedContext
    ) -> tuple[KnowledgeHit, ...]:
        return tuple(
            hit
            for owner_house, hit in self.hits
            if owner_house in (None, context.house_id)
            and command.query.casefold() in hit.excerpt.casefold()
        )


class FakeRequestPort:
    def __init__(self, cases: FakeCasePort) -> None:
        self.cases = cases
        self.requests: dict[UUID, tuple[UUID, RequestView]] = {}
        self.operations: dict[tuple[UUID, UUID], RequestView] = {}

    async def prepare(self, command: RequestPrepare, context: TrustedContext) -> RequestView:
        key = (context.house_id, command.operation_id)
        prior = self.operations.get(key)
        if prior is not None:
            return prior
        case = await self.cases.get(command.case_id, context)
        if case is None:
            raise ValueError("CASE_NOT_FOUND")
        if case.version != command.expected_case_version:
            raise ValueError("VERSION_CONFLICT")
        request = RequestView(
            request_id=uuid4(), case_id=case.case_id, draft_version=1, status="prepared"
        )
        self.requests[request.request_id] = (context.house_id, request)
        self.operations[key] = request
        return request

    async def submit(self, command: RequestSubmit, context: TrustedContext) -> RequestView:
        key = (context.house_id, command.operation_id)
        prior = self.operations.get(key)
        if prior is not None:
            return prior
        request = await self.get_status(command.request_id, context)
        if request is None:
            raise ValueError("REQUEST_NOT_FOUND")
        if request.draft_version != command.expected_draft_version:
            raise ValueError("VERSION_CONFLICT")
        submitted = request.model_copy(update={"status": "submitted"})
        self.requests[request.request_id] = (context.house_id, submitted)
        self.operations[key] = submitted
        return submitted

    async def get_status(self, request_id: UUID, context: TrustedContext) -> RequestView | None:
        item = self.requests.get(request_id)
        return item[1] if item is not None and item[0] == context.house_id else None
