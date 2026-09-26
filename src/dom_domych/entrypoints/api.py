"""Webhook ingress: secret → normalization → inbox commit → HTTP 200."""

import hmac
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.config import AppSettings
from dom_domych.infrastructure.max.updates import normalize_update
from dom_domych.infrastructure.postgres.inbox import save_inbox_event
from dom_domych.infrastructure.postgres.session import database_lifespan


async def _llm_is_ready(client: httpx.AsyncClient) -> bool:
    """Проверяет inference без генерации и не превращает его сбой в сбой ingress."""

    try:
        response = await client.get("/health")
        return response.is_success
    except httpx.HTTPError:
        return False


def create_app(
    database_url: str,
    webhook_secret: str,
    llm_base_url: str | None = None,
    *,
    llm_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    if not webhook_secret:
        raise ValueError("MAX_WEBHOOK_SECRET is required")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            sessions = await stack.enter_async_context(database_lifespan(database_url))
            app.state.sessions = sessions
            app.state.llm = None
            if llm_base_url is not None:
                app.state.llm = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=llm_base_url,
                        timeout=httpx.Timeout(2.0),
                        transport=llm_transport,
                    )
                )
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health/live")
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    @app.get("/ready")
    async def ready() -> dict[str, str]:
        sessions: async_sessionmaker[AsyncSession] = app.state.sessions
        try:
            async with sessions() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        llm: httpx.AsyncClient | None = app.state.llm
        if llm is None:
            return {"status": "degraded", "database": "ready", "llm": "not_configured"}
        llm_status = "ready" if await _llm_is_ready(llm) else "unavailable"
        return {
            "status": "ready" if llm_status == "ready" else "degraded",
            "database": "ready",
            "llm": llm_status,
        }

    @app.post("/webhook/max")
    async def webhook(
        request: Request,
        x_max_bot_api_secret: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if x_max_bot_api_secret is None or not hmac.compare_digest(
            x_max_bot_api_secret, webhook_secret
        ):
            raise HTTPException(status_code=401, detail="invalid webhook secret")
        if len(await request.body()) > 1_000_000:
            raise HTTPException(status_code=413, detail="update too large")
        try:
            raw = await request.json()
            if not isinstance(raw, dict):
                raise ValueError("update must be an object")
            received_at = datetime.now(UTC)
            source_key, event = normalize_update(raw, received_at)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="invalid MAX update") from exc
        sessions: async_sessionmaker[AsyncSession] = app.state.sessions
        async with sessions.begin() as session:
            inserted = await save_inbox_event(session, source_key, event, raw, received_at)
        return {"accepted": True, "new": inserted}

    return app


def create_app_from_env() -> FastAPI:
    """Uvicorn factory; polling mode не может случайно поднять webhook consumer."""

    settings = AppSettings.from_env()
    if settings.max_ingress_mode != "webhook":
        raise RuntimeError("API ingress requires MAX_INGRESS_MODE=webhook")
    return create_app(
        settings.database_url,
        settings.max_webhook_secret,
        settings.llm_base_url,
    )
