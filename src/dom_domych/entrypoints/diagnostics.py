"""Read-only, redacted diagnostics for durable runtime queues."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dom_domych.infrastructure.postgres.session import database_lifespan


@dataclass(frozen=True, slots=True)
class QueueHealth:
    statuses: dict[str, int]
    ready: int
    stale_leases: int


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    captured_at: str
    alembic_revision: str
    inbox: QueueHealth
    outbox: QueueHealth
    jobs: QueueHealth
    alerts: tuple[str, ...]


async def _queue_health(
    session: AsyncSession,
    table: str,
    *,
    ready_column: str,
    now: datetime,
) -> QueueHealth:
    if table not in {"inbox_events", "outbox_deliveries", "scheduled_jobs"}:
        raise ValueError("unsupported diagnostic table")
    if ready_column not in {"available_at", "due_at"}:
        raise ValueError("unsupported diagnostic timestamp")
    rows = await session.execute(
        text(f"SELECT status, count(*) FROM {table} GROUP BY status ORDER BY status")
    )
    statuses = {str(status): int(str(count)) for status, count in rows}
    ready = await session.scalar(
        text(f"SELECT count(*) FROM {table} WHERE status = 'pending' AND {ready_column} <= :now"),
        {"now": now},
    )
    stale = await session.scalar(
        text(f"SELECT count(*) FROM {table} WHERE status = 'processing' AND lease_until <= :now"),
        {"now": now},
    )
    return QueueHealth(statuses, int(ready or 0), int(stale or 0))


def _alerts(inbox: QueueHealth, outbox: QueueHealth, jobs: QueueHealth) -> tuple[str, ...]:
    alerts: list[str] = []
    for name, queue in (("inbox", inbox), ("outbox", outbox), ("jobs", jobs)):
        if queue.stale_leases:
            alerts.append(f"{name}.stale_leases")
    if inbox.statuses.get("dead", 0):
        alerts.append("inbox.dead")
    for status in ("dead", "failed", "delivery_unknown"):
        if outbox.statuses.get(status, 0):
            alerts.append(f"outbox.{status}")
    if jobs.statuses.get("dead", 0):
        alerts.append("jobs.dead")
    return tuple(alerts)


async def snapshot(database_url: str, now: datetime | None = None) -> RuntimeSnapshot:
    """Read aggregate queue state in a PostgreSQL read-only transaction."""

    captured_at = now or datetime.now(UTC)
    async with database_lifespan(database_url) as sessions:
        async with sessions.begin() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            inbox = await _queue_health(
                session, "inbox_events", ready_column="available_at", now=captured_at
            )
            outbox = await _queue_health(
                session, "outbox_deliveries", ready_column="available_at", now=captured_at
            )
            jobs = await _queue_health(
                session, "scheduled_jobs", ready_column="due_at", now=captured_at
            )
    return RuntimeSnapshot(
        captured_at=captured_at.isoformat(),
        alembic_revision=str(revision),
        inbox=inbox,
        outbox=outbox,
        jobs=jobs,
        alerts=_alerts(inbox, outbox, jobs),
    )


async def _main(*, fail_on_alert: bool) -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    result = await snapshot(database_url)
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 2 if fail_on_alert and result.alerts else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Redacted read-only status counts for inbox, outbox and scheduled jobs."
    )
    parser.add_argument("--fail-on-alert", action="store_true")
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(_main(fail_on_alert=arguments.fail_on_alert)))


if __name__ == "__main__":
    main()
