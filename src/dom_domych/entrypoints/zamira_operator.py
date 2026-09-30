"""Локальные команды доверенного оператора demo-исполнителя и документов."""

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from dom_domych.application.documents.cases import CaseDocumentPreparer
from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.application.jobs.inbox_worker import SystemClock
from dom_domych.domain.documents.snapshot import DocumentKind
from dom_domych.domain.executor.models import ExternalStatus
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_executor_models import DemoExecutorRow


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
    for command in ("list", "register", "status", "show", "done"):
        sub = commands.add_parser(command)
        sub.add_argument("--house-id", type=_uuid, required=True)
        if command != "list":
            target = sub.add_mutually_exclusive_group(required=True)
            target.add_argument("--request-id", type=_uuid)
            target.add_argument("--operation-id", type=_uuid)
        if command == "status":
            sub.add_argument("--status", choices=("in_progress", "done"), required=True)
        if command in ("status", "done"):
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


async def run_command(
    args: argparse.Namespace, database_url: str, clock: Clock | None = None
) -> str:
    """Доступ к локальному процессу/БД — граница operator trust, не команда бота."""
    clock = clock or SystemClock()
    async with database_lifespan(database_url) as sessions:
        async with sessions() as session:
            house = await session.get(HouseRow, args.house_id)
            if house is None or not house.demo:
                if getattr(args, "request_id", None) is not None:
                    raise PermissionError("DEMO_HOUSE_REQUIRED")
                raise ValueError("operator command is allowed only for an existing demo house")
            if args.command == "list":
                rows = (
                    await session.scalars(
                        select(DemoExecutorRow)
                        .where(DemoExecutorRow.house_id == args.house_id)
                        .order_by(DemoExecutorRow.submitted_at, DemoExecutorRow.id)
                    )
                ).all()
                return (
                    "\n".join(
                        f"{row.id} request={row.request_id} status={row.status} "
                        f"registration={row.registration_number or '-'}"
                        for row in rows
                    )
                    or "no demo operations"
                )
            operation_id = getattr(args, "operation_id", None)
            request_id: UUID | None
            if operation_id is not None:
                row = await session.scalar(
                    select(DemoExecutorRow).where(
                        DemoExecutorRow.id == operation_id,
                        DemoExecutorRow.house_id == args.house_id,
                    )
                )
                if row is None:
                    raise ValueError("demo operation is missing or belongs to another house")
                request_id = row.request_id
            else:
                request_id = getattr(args, "request_id", None)
            if request_id is None and args.command != "document":
                raise ValueError("request ID is required")
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
        if request_id is None:
            raise ValueError("request ID is required")
        operation = await executor.get_status(request_id, context)
        emitted = False
        if args.command == "register":
            operation, emitted = await executor.register(operation.operation_id, context)
        elif args.command in ("status", "done"):
            operation, emitted = await executor.set_status(
                operation.operation_id,
                ExternalStatus.DONE if args.command == "done" else ExternalStatus(args.status),
                args.event_id,
                context,
            )
        elif args.command != "show":
            raise ValueError("unsupported operator command")
        if operation_id is not None:
            return (
                f"{operation.operation_id} request={request_id} status={operation.status.value} "
                f"registration={operation.registration_number or '-'} emitted={emitted}"
            )
        return json.dumps(
            {
                "source": "demo_executor",
                "request_id": str(request_id),
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
