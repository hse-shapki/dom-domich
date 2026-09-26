"""K09: версия дела, evidence ref и событие в одной короткой транзакции."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.contracts import CaseKind, CaseView
from dom_domych.application.cases.evidence import EvidenceInput
from dom_domych.contracts.base import TrustedContext
from dom_domych.contracts.events import EntityEventPayload, EventEnvelope, EventName, EventSource
from dom_domych.infrastructure.postgres.case_models import (
    CaseEventRow,
    CaseEvidenceRow,
    CaseOperationRow,
    CaseRow,
)
from dom_domych.infrastructure.postgres.inbox import save_domain_event


class PostgresEvidenceWriter:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def add(self, command: EvidenceInput, context: TrustedContext, now: datetime) -> CaseView:
        payload = (
            f"{command.case_id}:{command.expected_version}:{command.file_key}:"
            f"{context.actor_id}:{context.event_id}"
        )
        command_hash = sha256(payload.encode()).hexdigest()
        async with self.sessions.begin() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"operation:{context.house_id}:{command.operation_id}"},
            )
            prior = await session.get(CaseOperationRow, (context.house_id, command.operation_id))
            if prior is not None:
                if prior.command_hash != command_hash:
                    raise ValueError("CONFLICT")
                return CaseView.model_validate_json(json.dumps(prior.result_view))
            row = await session.scalar(
                select(CaseRow)
                .where(CaseRow.id == command.case_id, CaseRow.house_id == context.house_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("CASE_NOT_FOUND")
            if row.version != command.expected_version:
                raise ValueError("VERSION_CONFLICT")
            if row.status == "closed":
                raise ValueError("INVALID_STATE")
            source_ref = f"event:{context.event_id}"
            existing = await session.scalar(
                select(CaseEvidenceRow).where(
                    CaseEvidenceRow.case_id == row.id,
                    CaseEvidenceRow.source_ref == source_ref,
                )
            )
            if existing is not None:
                raise ValueError("EVIDENCE_ALREADY_ATTACHED")
            session.add(
                CaseEvidenceRow(
                    id=uuid4(),
                    case_id=row.id,
                    house_id=context.house_id,
                    actor_id=context.actor_id,
                    source_ref=source_ref,
                    file_key=str(command.file_key) if command.file_key is not None else None,
                    assessment="pending",
                    created_at=now,
                )
            )
            previous_version = row.version
            row.version += 1
            view = CaseView(
                case_id=row.id,
                version=row.version,
                kind=CaseKind(row.kind),
                title=row.title,
                status=row.status,
                source_refs=(source_ref,),
            )
            evidence_event_id = uuid4()
            session.add(
                CaseEventRow(
                    id=evidence_event_id,
                    case_id=row.id,
                    house_id=context.house_id,
                    event_type="evidence.added",
                    before_version=previous_version,
                    after_version=row.version,
                    actor_id=context.actor_id,
                    source_message_id=context.event_id,
                    operation_id=command.operation_id,
                    occurred_at=now,
                    facts={"file_attached": command.file_key is not None},
                )
            )
            await save_domain_event(
                session,
                EventEnvelope(
                    event_id=evidence_event_id,
                    source=EventSource.DOMAIN,
                    source_key=f"evidence-added:{command.operation_id}",
                    name=EventName.EVIDENCE_ADDED,
                    occurred_at=now,
                    received_at=now,
                    correlation_id=context.correlation_id,
                    house_id=context.house_id,
                    entity=EntityEventPayload(
                        entity_id=row.id,
                        entity_version=row.version,
                        case_id=row.id,
                        causation_id=context.event_id,
                    ),
                ),
            )
            session.add(
                CaseOperationRow(
                    house_id=context.house_id,
                    operation_id=command.operation_id,
                    case_id=row.id,
                    command_hash=command_hash,
                    result_view=view.model_dump(mode="json"),
                )
            )
            return view
