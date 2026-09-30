"""Локальные доверенные команды для демонстрационного исполнителя Z16."""

import argparse
import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.domain.executor.models import ExternalStatus
from dom_domych.infrastructure.postgres.demo_executor import PostgresDemoExecutor
from dom_domych.infrastructure.postgres.models import HouseRow
from dom_domych.infrastructure.postgres.session import database_lifespan
from dom_domych.infrastructure.postgres.z_executor_models import DemoExecutorRow


@dataclass(frozen=True)
class OperatorContext:
    house_id: UUID
    capabilities: frozenset[str]


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ожидается UUID") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Доверенные команды demo executor; DATABASE_URL только из окружения."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "register", "done"):
        command = commands.add_parser(name)
        command.add_argument("--house-id", type=_uuid, required=True)
        if name != "list":
            command.add_argument("--operation-id", type=_uuid, required=True)
        if name == "done":
            command.add_argument("--event-id", type=_uuid, required=True)
    return parser


async def run_command(args: argparse.Namespace, database_url: str) -> str:
    """Не допускает live-дом и не обходит переходы DemoExecutorService."""

    async with database_lifespan(database_url) as sessions:
        async with sessions() as session:
            house = await session.get(HouseRow, args.house_id)
            if house is None or not house.demo:
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
        service = DemoExecutorService(PostgresDemoExecutor(sessions, SystemClock()), SystemClock())
        if args.command == "register":
            context = OperatorContext(args.house_id, frozenset({"demo_executor.register"}))
            operation, emitted = await service.register(args.operation_id, context)
        elif args.command == "done":
            context = OperatorContext(args.house_id, frozenset({"demo_executor.operator"}))
            operation, emitted = await service.set_status(
                args.operation_id, ExternalStatus.DONE, args.event_id, context
            )
        else:
            raise ValueError("unsupported operator command")
        return (
            f"operation={operation.operation_id} status={operation.status.value} "
            f"registration={operation.registration_number or '-'} emitted={emitted}"
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
