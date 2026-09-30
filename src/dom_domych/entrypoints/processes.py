"""Отдельные process loops для inbox, scheduler, outbox и служебных задач."""

import argparse
import asyncio
import signal
from datetime import timedelta
from typing import Protocol

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
from dom_domych.application.cases.production import register_problem_events
from dom_domych.application.documents.followup import RequestComplaintEventHandler
from dom_domych.application.documents.production import RequestDocumentEventHandler
from dom_domych.application.documents.worker import DocumentWorker
from dom_domych.application.executor.production import DemoSubmitAdapter
from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.application.initiatives.production import register_initiative_events
from dom_domych.application.jobs.inbox_worker import (
    EventDispatcher,
    InboxWorker,
    SystemClock,
)
from dom_domych.application.jobs.maintenance import RetentionMaintenance
from dom_domych.application.jobs.scheduler import JobScheduler, RevisionRouter
from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.application.polls.production import (
    PostgresPollCallbackProcessor,
    register_poll_callbacks,
)
from dom_domych.application.requests.emergency_runtime import EmergencyAudienceEventHandler
from dom_domych.application.resolution.production import register_z_poll_events
from dom_domych.config import AppSettings
from dom_domych.contracts.events import EventName
from dom_domych.infrastructure.documents.renderer import PdfRenderer
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.llm.llama_server import LlamaServerPort
from dom_domych.infrastructure.llm.ollama import OllamaPort
from dom_domych.infrastructure.max.client import MAX_API_BASE_URL, MaxApiClient
from dom_domych.infrastructure.max.media import MaxMediaTransport
from dom_domych.infrastructure.max.onboarding import MaxOnboardingHandler
from dom_domych.infrastructure.max.polling import MaxPollingConsumer
from dom_domych.infrastructure.max.rate_limit import MaxRateLimits
from dom_domych.infrastructure.max.tls import max_ssl_context
from dom_domych.infrastructure.postgres.demo_executor import (
    PostgresDemoExecutor,
    PostgresExecutorPort,
)
from dom_domych.infrastructure.postgres.documents import PostgresDocuments
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
    inner: LlmPort
    if settings.llm_backend == "ollama":
        inner = OllamaPort(client, settings.llm_model, max_tokens=settings.llm_max_tokens)
    else:
        inner = LlamaServerPort(client, settings.llm_model, max_tokens=settings.llm_max_tokens)
    return RetryingLlmPort(
        inner,
        timeout_seconds=settings.llm_timeout_seconds,
        attempts=settings.llm_attempts,
    )


def _k_runtime(
    sessions: async_sessionmaker[AsyncSession], llm: LlmPort, clock: SystemClock
) -> tuple[EventDispatcher, RevisionRouter]:
    executor = PostgresDemoExecutor(sessions, clock)
    coordinator = build_k_coordinator(
        sessions, llm, clock, DemoSubmitAdapter(DemoExecutorService(executor, clock))
    )
    dispatcher, revisions = EventDispatcher({}), RevisionRouter()
    register_problem_events(dispatcher, sessions, clock)
    register_initiative_events(dispatcher, sessions, clock)
    resolution = register_z_poll_events(dispatcher, revisions, sessions, clock)
    dispatcher.register(EventName.REQUEST_REGISTERED, RequestDocumentEventHandler(sessions, clock))
    dispatcher.register(
        EventName.REQUEST_DEADLINE_REACHED, RequestComplaintEventHandler(sessions, clock)
    )
    register_k_continuations(
        dispatcher,
        revisions,
        sessions,
        clock,
        coordinator,
        PostgresExecutorPort(executor),
        PostgresDocuments(sessions),
        status_after_request=resolution.handle_status,
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
    max_verify = max_ssl_context()
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(
            base_url=MAX_API_BASE_URL,
            timeout=max_timeout,
            verify=max_verify,
            trust_env=False,
        ) as max_http,
        httpx.AsyncClient(base_url=settings.llm_base_url, timeout=llm_timeout) as llm_http,
    ):
        clock = SystemClock()
        llm = _llm(settings, llm_http)
        executor = PostgresDemoExecutor(sessions, clock)
        coordinator = build_k_coordinator(
            sessions, llm, clock, DemoSubmitAdapter(DemoExecutorService(executor, clock))
        )
        dispatcher, revisions = EventDispatcher({}), RevisionRouter()
        register_problem_events(dispatcher, sessions, clock)
        register_initiative_events(dispatcher, sessions, clock)
        dispatcher.register(
            EventName.EMERGENCY_DETECTED, EmergencyAudienceEventHandler(sessions, clock)
        )
        resolution = register_z_poll_events(dispatcher, revisions, sessions, clock)
        dispatcher.register(
            EventName.REQUEST_REGISTERED, RequestDocumentEventHandler(sessions, clock)
        )
        max_client = MaxApiClient(max_http, settings.max_bot_token, MaxRateLimits())
        onboarding = MaxOnboardingHandler(
            sessions,
            max_client,
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
        register_poll_callbacks(
            dispatcher, PostgresPollCallbackProcessor(sessions, max_client, clock)
        )
        dispatcher.register(
            EventName.REQUEST_DEADLINE_REACHED, RequestComplaintEventHandler(sessions, clock)
        )
        register_k_continuations(
            dispatcher,
            revisions,
            sessions,
            clock,
            coordinator,
            PostgresExecutorPort(executor),
            PostgresDocuments(sessions),
            status_after_request=resolution.handle_status,
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
    max_verify = max_ssl_context()
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(
            base_url=MAX_API_BASE_URL,
            timeout=timeout,
            verify=max_verify,
            trust_env=False,
        ) as api_http,
        httpx.AsyncClient(timeout=timeout, verify=max_verify, trust_env=False) as media_http,
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


async def run_documents() -> None:
    settings = AppSettings.from_env()
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    clock = SystemClock()
    async with database_lifespan(settings.database_url) as sessions:
        async with PdfRenderer(max_workers=2) as renderer:
            worker = DocumentWorker(
                sessions,
                LocalFileStore(settings.file_store_dir, clock),
                renderer,
                clock,
                f"{settings.worker_id}:documents",
            )
            await _run_once_loop(stop, worker, "documents")


async def run_polling() -> None:
    settings = AppSettings.from_env(require_max_token=True)
    if settings.max_ingress_mode != "polling":
        raise RuntimeError("polling requires MAX_INGRESS_MODE=polling")
    assert settings.max_bot_token is not None
    stop = asyncio.Event()
    _install_stop_handlers(stop)
    timeout = httpx.Timeout(connect=5, read=45, write=10, pool=5)
    max_verify = max_ssl_context()
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(
            base_url=MAX_API_BASE_URL,
            timeout=timeout,
            verify=max_verify,
            trust_env=False,
        ) as api_http,
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
        "process", choices=("inbox", "scheduler", "outbox", "documents", "polling", "maintenance")
    )
    process = parser.parse_args().process
    if process == "inbox":
        coroutine = run_inbox()
    elif process == "scheduler":
        coroutine = run_scheduler()
    elif process == "outbox":
        coroutine = run_outbox()
    elif process == "documents":
        coroutine = run_documents()
    elif process == "polling":
        coroutine = run_polling()
    else:
        coroutine = run_maintenance()
    asyncio.run(coroutine)


if __name__ == "__main__":
    main()
