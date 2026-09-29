"""Локальные команды доверенного оператора demo-исполнителя и документов."""

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from dom_domych.application.documents.cases import CaseDocumentPreparer
from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.application.jobs.inbox_worker import SystemClock
from dom_domych.domain.documents.snapshot import DocumentKind
from dom_domych.domain.executor.models import ExternalStatus
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.session import database_lifespan


@dataclass(frozen=True)
class _OperatorContext:
    house_id: UUID
    actor_id: UUID | None = None
    capabilities: frozenset[str] = frozenset(
        {
            "demo_executor.register",
            "demo_executor.operator",
            "document.prepare",
            "document.notice_register",
        }
    )


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ожидается UUID") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Локальный demo operator. DATABASE_URL из окружения; только demo-дома."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("register", "status", "show"):
        sub = commands.add_parser(command)
        sub.add_argument("--house-id", type=_uuid, required=True)
        sub.add_argument("--request-id", type=_uuid, required=True)
        if command == "status":
            sub.add_argument("--status", choices=("in_progress", "done"), required=True)
            sub.add_argument(
                "--event-id",
                type=_uuid,
                required=True,
                help="Один UUID сохраняется для всех повторов команды.",
            )
    document = commands.add_parser(
        "document",
        description="Подготовить приватный PDF для уполномоченного подтверждённого жителя.",
    )
    document.add_argument("--house-id", type=_uuid, required=True)
    document.add_argument("--case-id", type=_uuid, required=True)
    document.add_argument("--recipient-id", type=_uuid, required=True)
    document.add_argument(
        "--kind",
        choices=("resident_position", "notification_register", "complaint_draft"),
        required=True,
    )
    document.add_argument("--operation-key", required=True)
    return parser


async def run_command(args: argparse.Namespace, database_url: str) -> str:
    """Доступ к локальному процессу/БД — граница operator trust, не команда бота."""
    clock = SystemClock()
    async with database_lifespan(database_url) as sessions:
        async with sessions() as session:
            house = await session.get(HouseRow, args.house_id)
            if house is None or not house.demo:
                raise PermissionError("DEMO_HOUSE_REQUIRED")
        if args.command == "document":
            ref = await CaseDocumentPreparer(sessions, clock).prepare(
                DocumentKind(args.kind),
                args.case_id,
                _OperatorContext(args.house_id, args.recipient_id),
                operation_key=args.operation_key,
            )
            return json.dumps(
                {
                    "document_id": str(ref.document_id),
                    "status": ref.status,
                    "snapshot_sha256": ref.snapshot_hash,
                },
                ensure_ascii=False,
            )
        executor = DemoExecutorService(PostgresDemoExecutor(sessions, clock), clock)
        context = _OperatorContext(args.house_id)
        operation = await executor.get_status(args.request_id, context)
        emitted = False
        if args.command == "register":
            operation, emitted = await executor.register(operation.operation_id, context)
        elif args.command == "status":
            operation, emitted = await executor.set_status(
                operation.operation_id, ExternalStatus(args.status), args.event_id, context
            )
        elif args.command != "show":
            raise ValueError("unsupported operator command")
        return json.dumps(
            {
                "source": "demo_executor",
                "request_id": str(args.request_id),
                "operation_id": str(operation.operation_id),
                "registration": operation.registration_number,
                "external_status": operation.status.value,
                "event_emitted": emitted,
            },
            ensure_ascii=False,
        )


async def _main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    print(await run_command(args, database_url))


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
