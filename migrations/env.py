"""Alembic environment для общего metadata; новые треки импортируют свои models здесь."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from dom_domych.infrastructure.postgres import (
    agent_models,  # noqa: F401
    case_models,  # noqa: F401
    knowledge_models,  # noqa: F401
    request_models,  # noqa: F401
    z_audience_models,  # noqa: F401
    z_document_models,  # noqa: F401
    z_followup_models,  # noqa: F401
    z_initiative_models,  # noqa: F401
    z_poll_models,  # noqa: F401
)
from dom_domych.infrastructure.postgres import models as core_models  # noqa: F401
from dom_domych.infrastructure.postgres.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Эти pgvector-объекты условно создаются объединёнными K migrations, когда расширение
# доступно. Репозитории обращаются к ним через проверяемый raw SQL, поэтому ORM metadata
# намеренно содержит только обязательный JSONB fallback. Не предлагать destructive drop
# на целевом PG17/pgvector во время общей проверки истории A14.
_OPTIONAL_VECTOR_COLUMNS = {
    ("cases", "embedding_vector"),
    ("knowledge_chunks", "embedding_vector"),
}
_OPTIONAL_VECTOR_INDEXES = {"ix_cases_vector", "ix_knowledge_chunks_vector"}


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    if not reflected or compare_to is not None:
        return True
    if type_ == "column":
        table = getattr(getattr(object_, "table", None), "name", None)
        return (table, name) not in _OPTIONAL_VECTOR_COLUMNS
    if type_ == "index":
        return name not in _OPTIONAL_VECTOR_INDEXES
    return True


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for migrations")
    if not value.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use postgresql+asyncpg")
    return value


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
