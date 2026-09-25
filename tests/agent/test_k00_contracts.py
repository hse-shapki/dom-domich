from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from dom_domych.agent.contracts import (
    TOOL_INPUTS,
    CaseAttachMessage,
    CaseCreate,
    CaseKind,
    CaseSearch,
    KnowledgeSearch,
    RequestPrepare,
    RequestSubmit,
    TrustedContext,
)
from dom_domych.agent.fakes import FakeCasePort, FakeKnowledgePort, FakeRequestPort
from dom_domych.agent.tool_handlers import KToolHandlers
from dom_domych.contracts.base import ExecutionMode, PrincipalType
from dom_domych.contracts.errors import ErrorCode


def _context(house_id: UUID | None = None) -> TrustedContext:
    return TrustedContext(
        house_id=house_id if house_id is not None else uuid4(),
        actor_id=uuid4(),
        event_id=uuid4(),
        run_id=uuid4(),
        capabilities=frozenset(),
        principal_type=PrincipalType.RESIDENT,
        correlation_id=uuid4(),
        mode=ExecutionMode.DEMO,
    )


def test_k_tools_exclude_trusted_identity_fields() -> None:
    for name, command in TOOL_INPUTS.items():
        assert "house_id" not in command.model_fields, name
        assert "actor_id" not in command.model_fields, name
        assert command.model_json_schema()
    with pytest.raises(ValidationError):
        CaseSearch.model_validate({"query": "Лампа на лестнице", "house_id": str(uuid4())})


@pytest.mark.asyncio
async def test_fake_case_and_request_keep_tenant_version_and_registration_separate() -> None:
    context = _context()
    other_house = _context()
    cases = FakeCasePort()
    requests = FakeRequestPort(cases)
    create = CaseCreate(
        kind=CaseKind.PROBLEM,
        title="Лампа на лестнице",
        description="Не горит свет",
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )
    case = await cases.create(create, context)
    assert (await cases.create(create, context)).case_id == case.case_id
    assert await cases.get(case.case_id, other_house) is None
    assert len(await cases.search(CaseSearch(query="лампа"), context)) == 1
    assert await cases.search(CaseSearch(query="лампа"), other_house) == ()

    message_id = uuid4()
    attached = await cases.attach_message(
        CaseAttachMessage(
            case_id=case.case_id,
            message_id=message_id,
            expected_version=1,
            operation_id=uuid4(),
        ),
        context,
    )
    assert attached.version == 2
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        await cases.attach_message(
            CaseAttachMessage(
                case_id=case.case_id,
                message_id=uuid4(),
                expected_version=1,
                operation_id=uuid4(),
            ),
            context,
        )

    prepare = RequestPrepare(
        case_id=case.case_id,
        expected_case_version=2,
        responsible_id=uuid4(),
        source_refs=("source:1",),
        operation_id=uuid4(),
    )
    request = await requests.prepare(prepare, context)
    assert request.status == "prepared"
    assert request.registration_id is None
    assert await requests.get_status(request.request_id, other_house) is None
    submitted = await requests.submit(
        RequestSubmit(
            request_id=request.request_id, expected_draft_version=1, operation_id=uuid4()
        ),
        context,
    )
    assert submitted.status == "submitted"
    assert submitted.registration_id is None


@pytest.mark.asyncio
async def test_fake_knowledge_returns_no_unverified_rule_by_default() -> None:
    assert await FakeKnowledgePort().search(KnowledgeSearch(query="срок ремонта"), _context()) == ()


@pytest.mark.asyncio
async def test_k00_handler_uses_a01_context_and_rejects_forged_house() -> None:
    context = _context()
    cases = FakeCasePort()
    handlers = KToolHandlers(cases, FakeKnowledgePort(), FakeRequestPort(cases))
    allowed = context.model_copy(update={"capabilities": frozenset({"case.write", "case.read"})})
    command = CaseCreate(
        kind=CaseKind.PROBLEM,
        title="Лампа на лестнице",
        description="Темно у лифта",
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )
    forged = command.model_dump(mode="json") | {"house_id": str(uuid4())}
    from json import dumps

    rejected = await handlers.execute("case.create", dumps(forged), allowed)
    assert rejected.ok is False
    assert rejected.error is not None and rejected.error.code == ErrorCode.VALIDATION_ERROR
    created = await handlers.execute("case.create", command.model_dump_json(), allowed)
    assert created.ok is True
    assert created.data is not None
    case_id = UUID(str(created.data["case_id"]))
    assert await cases.get(case_id, context) is not None
    foreign = await handlers.execute(
        "case.get",
        f'{{"case_id":"{case_id}"}}',
        _context().model_copy(update={"capabilities": frozenset({"case.read"})}),
    )
    assert foreign.ok is False


@pytest.mark.asyncio
async def test_k00_handler_rejects_missing_capability_before_write() -> None:
    cases = FakeCasePort()
    handlers = KToolHandlers(cases, FakeKnowledgePort(), FakeRequestPort(cases))
    command = CaseCreate(
        kind=CaseKind.PROBLEM,
        title="Лампа на лестнице",
        description="Темно у лифта",
        source_message_id=uuid4(),
        operation_id=uuid4(),
    )
    result = await handlers.execute("case.create", command.model_dump_json(), _context())
    assert result.ok is False
    assert result.error is not None and result.error.code == ErrorCode.FORBIDDEN
    assert cases.cases == {}
