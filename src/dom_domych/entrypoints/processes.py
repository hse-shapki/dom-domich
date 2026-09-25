"""Отдельные process loops для outbox и dev polling."""

import argparse
import asyncio
import signal

import httpx
import structlog

from dom_domych.application.jobs.inbox_worker import SystemClock
from dom_domych.application.notifications.worker import DeliveryWorker
from dom_domych.config import AppSettings
from dom_domych.infrastructure.files.local import LocalFileStore
from dom_domych.infrastructure.max.client import MAX_API_BASE_URL, MaxApiClient
from dom_domych.infrastructure.max.media import MaxMediaTransport
from dom_domych.infrastructure.max.polling import MaxPollingConsumer
from dom_domych.infrastructure.max.rate_limit import MaxRateLimits
from dom_domych.infrastructure.postgres.session import database_lifespan

logger = structlog.get_logger()


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
        consumer = MaxPollingConsumer(
            sessions, MaxApiClient(api_http, settings.max_bot_token, MaxRateLimits())
        )
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("process", choices=("outbox", "polling"))
    process = parser.parse_args().process
    asyncio.run(run_outbox() if process == "outbox" else run_polling())


if __name__ == "__main__":
    main()
