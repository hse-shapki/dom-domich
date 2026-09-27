"""Локальные команды доверенного оператора для настройки demo-онбординга."""

import argparse
import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from dom_domych.application.residents.enrollment import (
    DemoEnrollmentService,
    TrustedDemoOperator,
)
from dom_domych.infrastructure.postgres.enrollment import PostgresEnrollment
from dom_domych.infrastructure.postgres.session import database_lifespan


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ожидается UUID") from exc


def _positive_hours(value: str) -> int:
    try:
        hours = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ожидается целое число часов") from exc
    if not 1 <= hours <= 168:
        raise argparse.ArgumentTypeError("срок должен быть от 1 до 168 часов")
    return hours


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Настройка demo-онбординга; DATABASE_URL читается только из окружения."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    invitation = commands.add_parser(
        "issue-invitation", description="Выдать одноразовый код после очной demo-проверки."
    )
    invitation.add_argument("--house-id", type=_uuid, required=True)
    invitation.add_argument("--residency-id", type=_uuid, required=True)
    invitation.add_argument(
        "--adult-verified",
        action="store_true",
        required=True,
        help="Подтвердить, что оператор проверил совершеннолетие.",
    )
    invitation.add_argument("--ttl-hours", type=_positive_hours, default=24)

    house_chat = commands.add_parser(
        "bind-house-chat", description="Привязать числовой MAX chat ID к demo-дому."
    )
    house_chat.add_argument("--house-id", type=_uuid, required=True)
    house_chat.add_argument("--max-chat-id", required=True)
    return parser


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


async def run_command(args: argparse.Namespace, database_url: str) -> str:
    """Выполнить одну operator-команду в короткой транзакции."""

    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            service = DemoEnrollmentService(PostgresEnrollment(session), _SystemClock())
            if args.command == "issue-invitation":
                operator = TrustedDemoOperator(args.house_id, frozenset({"demo.residency_confirm"}))
                token = await service.issue_invitation(
                    args.residency_id,
                    operator,
                    adult_verified=args.adult_verified,
                    ttl=timedelta(hours=args.ttl_hours),
                )
                return token
            if args.command == "bind-house-chat":
                operator = TrustedDemoOperator(args.house_id, frozenset({"demo.house_chat_bind"}))
                await service.connect_house_chat(args.max_chat_id, operator)
                return "ok"
    raise RuntimeError("unsupported operator command")


async def _main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = await run_command(args, _database_url())
    print(result)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
