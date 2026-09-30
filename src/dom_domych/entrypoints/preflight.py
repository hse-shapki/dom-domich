"""Redacted A-MVP-1 preflight for the composed PostgreSQL/MAX/LLM runtime."""

from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy import text

from dom_domych.agent.llm import LlmPort, RetryingLlmPort
from dom_domych.config import AppSettings
from dom_domych.infrastructure.llm.llama_server import LlamaServerPort
from dom_domych.infrastructure.llm.ollama import OllamaPort
from dom_domych.infrastructure.max.client import MAX_API_BASE_URL, MaxApiClient
from dom_domych.infrastructure.max.tls import max_ssl_context
from dom_domych.infrastructure.postgres.session import database_lifespan


def _llm(settings: AppSettings, client: httpx.AsyncClient) -> LlmPort:
    assert settings.llm_model is not None
    inner: LlmPort
    if settings.llm_backend == "ollama":
        inner = OllamaPort(client, settings.llm_model, max_tokens=64)
    else:
        inner = LlamaServerPort(client, settings.llm_model, max_tokens=64)
    return RetryingLlmPort(inner, timeout_seconds=settings.llm_timeout_seconds, attempts=1)


async def run() -> dict[str, object]:
    settings = AppSettings.from_env(require_max_token=True, require_llm=True)
    assert settings.max_bot_token is not None
    assert settings.llm_base_url is not None
    async with (
        database_lifespan(settings.database_url) as sessions,
        httpx.AsyncClient(
            base_url=MAX_API_BASE_URL,
            timeout=10,
            verify=max_ssl_context(),
            trust_env=False,
        ) as max_http,
        httpx.AsyncClient(
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
        ) as llm_http,
    ):
        async with sessions() as session:
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            vector = await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        max_client = MaxApiClient(max_http, settings.max_bot_token)
        identity = await max_client.get_me()
        webhooks = await max_client.list_webhooks()
        response = await _llm(settings, llm_http).complete(
            [
                {"role": "system", "content": "Ответь одним словом по-русски."},
                {"role": "user", "content": "Готов?"},
            ],
            [],
        )
        if not response.text.strip() or response.tool_calls:
            raise RuntimeError("configured model did not return a plain readiness response")
        if settings.max_ingress_mode == "polling" and webhooks:
            raise RuntimeError("polling configured while a MAX webhook is active")
        return {
            "database": "ready",
            "alembic_revision": revision,
            "pgvector": vector,
            "max": "ready",
            "max_bot_user_id": identity.user_id,
            "ingress": settings.max_ingress_mode,
            "webhook_count": len(webhooks),
            "llm": "ready",
            "llm_backend": settings.llm_backend,
            "llm_model": settings.llm_model,
        }


def main() -> None:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
