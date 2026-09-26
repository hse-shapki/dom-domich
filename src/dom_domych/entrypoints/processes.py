"""Отдельные process loops для inbox, scheduler, outbox и служебных задач."""

import argparse
import asyncio
import signal
from datetime import timedelta
from typing import Protocol
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.agent.llm import LlmPort, RetryingLlmPort
from dom_domych.application.agent.composition import (
    build_k_coordinator,
    build_k_message_agent,
    register_k_continuations,
)
from dom_domych.application.agent.messages import register_message_agent
from dom_domych.application.jobs.inbox_worker import (
    EventDispatcher,
    InboxWorker,
    SystemClock,
)
from dom_domych.application.jobs.maintenance import RetentionMaintenance
from dom_domych.application.jobs.scheduler import JobScheduler, RevisionRouter
from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.config import AppSettings
from dom_domych.contracts.events import EventName
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation
from dom_domych.domain.ports.core import DocumentRef, RequestRef
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.llm.llama_server import LlamaServerPort
from dom_domych.infrastructure.max.client import MAX_API_BASE_URL, MaxApiClient
from dom_domych.infrastructure.max.media import MaxMediaTransport
from dom_domych.infrastructure.max.onboarding import MaxOnboardingHandler
from dom_domych.infrastructure.max.polling import MaxPollingConsumer
from dom_domych.infrastructure.max.rate_limit import MaxRateLimits
from dom_domych.infrastructure.postgres.session import database_lifespan

logger = structlog.get_logger()

_RESIDENT_AGENT_CAPABILITIES = frozenset(
    {
        "case.read",
        "case.write",
        "knowledge.read",
        "request.read",
        "request.write",
        "emergency.handle",
    }
)


class _RunOnce(Protocol):
    async def run_once(self) -> bool: ...


class _UnavailableZPorts:
    """Не подтверждает Z-действие, пока production repository не подключён."""

    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation:
        raise RuntimeError("Z_EXECUTOR_NOT_CONFIGURED")

    async def get_status(self, request_id: UUID, house_id: UUID) -> RequestRef:
        raise RuntimeError("Z_EXECUTOR_NOT_CONFIGURED")

    async def get(self, document_id: UUID, house_id: UUID) -> DocumentRef | None:
        raise RuntimeError("Z_DOCUMENT_REPOSITORY_NOT_CONFIGURED")


async def _wait_or_stop(stop: asyncio.Event, delay: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        pass


def _install_stop_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass


async def _run_once_loop(stop: asyncio.Event, worker: _RunOnce, process: str) -> None:
    failures = 0
    while not stop.is_set():
        try:
            worked = await worker.run_once()
            failures = 0
            if not worked:
                await _wait_or_stop(stop, 0.5)
        except Exception as exc:
            failures += 1
            logger.error(
                "process_loop_failed",
                process=process,
                error=type(exc).__name__,
                failures=failures,
            )
            await _wait_or_stop(stop, min(30.0, float(2 ** min(failures, 5))))


def _llm(settings: AppSettings, client: httpx.AsyncClient) -> LlmPort:
    assert settings.llm_model is not None
    return RetryingLlmPort(
        LlamaServerPort(client, settings.llm_model, max_tokens=settings.llm_max_tokens),
        timeout_seconds=settings.llm_timeout_seconds,
        attempts=settings.llm_attempts,
    )


def _k_runtime(
    sessions: async_sessionmaker[AsyncSession], llm: LlmPort, clock: SystemClock
) -> tuple[EventDispatcher, RevisionRouter]:
    unavailable = _UnavailableZPorts()
    coordinator = build_k_coordinator(sessions, llm, clock, unavailable)
    dispatcher, revisions = EventDispatcher({}), RevisionRouter()
    register_k_continuations(
        dispatcher,
        revisions,
        sessions,
        clock,
        coordinator,
        unavailable,
        unavailable,
    )
    return dispatcher, revisions


async def run_inbox() -> None:
    settings = AppSettings.from_env(require_max_token=True, require_llm=True)
    assert settings.max_bot_token is not None
    assert settings.llm_base_url is not None
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    max_timeout = httpx.Timeout(connect=5, read=30, write=30, pool=5)
    llm_timeout = httpx.Timeout(settings.llm_timeout_seconds)
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(base_url=MAX_API_BASE_URL, timeout=max_timeout) as max_http,
        httpx.AsyncClient(base_url=settings.llm_base_url, timeout=llm_timeout) as llm_http,
    ):
        clock = SystemClock()
        llm = _llm(settings, llm_http)
        unavailable = _UnavailableZPorts()
        coordinator = build_k_coordinator(sessions, llm, clock, unavailable)
        dispatcher, revisions = EventDispatcher({}), RevisionRouter()
        onboarding = MaxOnboardingHandler(
            sessions,
            MaxApiClient(max_http, settings.max_bot_token, MaxRateLimits()),
            clock,
        )
        for event_name in {
            EventName.MESSAGE_RECEIVED,
            EventName.BOT_STARTED,
            EventName.BOT_STOPPED,
        }:
            dispatcher.register(event_name, onboarding.handle)
        register_message_agent(
            dispatcher,
            build_k_message_agent(
                sessions,
                llm,
                clock,
                coordinator,
                _RESIDENT_AGENT_CAPABILITIES,
            ),
        )
        register_k_continuations(
            dispatcher,
            revisions,
            sessions,
            clock,
            coordinator,
            unavailable,
            unavailable,
        )
        worker = InboxWorker(sessions, dispatcher, clock, f"{settings.worker_id}:inbox")
        await _run_once_loop(stop, worker, "inbox")


async def run_scheduler() -> None:
    settings = AppSettings.from_env(require_llm=True)
    assert settings.llm_base_url is not None
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(
            base_url=settings.llm_base_url,
            timeout=httpx.Timeout(settings.llm_timeout_seconds),
        ) as llm_http,
    ):
        clock = SystemClock()
        dispatcher, revisions = _k_runtime(sessions, _llm(settings, llm_http), clock)
        worker = JobScheduler(
            sessions,
            dispatcher,
            revisions,
            clock,
            f"{settings.worker_id}:scheduler",
        )
        await _run_once_loop(stop, worker, "scheduler")


async def run_outbox() -> None:
    settings = AppSettings.from_env(require_max_token=True)
    assert settings.max_bot_token is not None
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    timeout = httpx.Timeout(connect=5, read=30, write=30, pool=5)
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(base_url=MAX_API_BASE_URL, timeout=timeout) as api_http,
        httpx.AsyncClient(timeout=timeout) as media_http,
    ):
        max_api = MaxApiClient(api_http, settings.max_bot_token, MaxRateLimits())
        clock = SystemClock()
        worker = DeliveryWorker(
            sessions,
            max_api,
            clock,
            settings.worker_id,
            media=MaxMediaTransport(media_http, max_api),
            files=LocalFileStore(settings.file_store_dir, clock),
        )
        failures = 0
        while not stop.is_set():
            try:
                worked = await worker.run_once()
                failures = 0
                if not worked:
                    await _wait_or_stop(stop, 0.5)
            except Exception as exc:
                failures += 1
                logger.error("outbox_loop_failed", error=type(exc).__name__, failures=failures)
                await _wait_or_stop(stop, min(30.0, float(2 ** min(failures, 5))))


async def run_polling() -> None:
    settings = AppSettings.from_env(require_max_token=True)
    if settings.max_ingress_mode != "polling":
        raise RuntimeError("polling requires MAX_INGRESS_MODE=polling")
    assert settings.max_bot_token is not None
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    timeout = httpx.Timeout(connect=5, read=45, write=10, pool=5)
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(base_url=MAX_API_BASE_URL, timeout=timeout) as api_http,
    ):
        max_api = MaxApiClient(api_http, settings.max_bot_token, MaxRateLimits())
        if await max_api.list_webhooks():
            raise RuntimeError("polling refused while MAX webhook subscription is active")
        consumer = MaxPollingConsumer(sessions, max_api)
        failures = 0
        while not stop.is_set():
            try:
                count = await consumer.poll_once()
                failures = 0
                if count == 0:
                    await _wait_or_stop(stop, 0.25)
            except Exception as exc:
                failures += 1
                logger.error("polling_loop_failed", error=type(exc).__name__, failures=failures)
                await _wait_or_stop(stop, min(30.0, float(2 ** min(failures, 5))))


async def run_maintenance() -> None:
    settings = AppSettings.from_env()
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    clock = SystemClock()
    async with database_lifespan(settings.database_url) as sessions:
        maintenance = RetentionMaintenance(
            sessions,
            LocalFileStore(settings.file_store_dir, clock),
            clock,
            timedelta(days=settings.payload_retention_days),
        )
        while not stop.is_set():
            try:
                redacted, deleted_files = await maintenance.run_once()
                logger.info(
                    "retention_completed",
                    inbox_events=redacted.inbox_events,
                    outbox_deliveries=redacted.outbox_deliveries,
                    deleted_files=deleted_files,
                )
            except Exception as exc:
                logger.error("retention_failed", error=type(exc).__name__)
            await _wait_or_stop(stop, 3600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "process", choices=("inbox", "scheduler", "outbox", "polling", "maintenance")
    )
    process = parser.parse_args().process
    if process == "inbox":
        coroutine = run_inbox()
    elif process == "scheduler":
        coroutine = run_scheduler()
    elif process == "outbox":
        coroutine = run_outbox()
    elif process == "polling":
        coroutine = run_polling()
    else:
        coroutine = run_maintenance()
    asyncio.run(coroutine)


if __name__ == "__main__":
    main()
