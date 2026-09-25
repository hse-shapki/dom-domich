# Прямые зависимости Python

Аудит A00 от 25.09.2026: лицензии прямых установленных пакетов сверены с `importlib.metadata` после `uv sync --locked`. Перед выпуском A17 нужно повторить проверку **транзитивных пакетов** и сохранить NOTICE. Это не подтверждение лицензии будущей модели или внешнего сервиса.

| Пакет | Лицензия проекта | Источник |
|---|---|---|
| FastAPI | MIT | https://github.com/fastapi/fastapi/blob/master/LICENSE |
| Uvicorn | BSD-3-Clause | https://github.com/encode/uvicorn/blob/master/LICENSE.md |
| Pydantic | MIT | https://github.com/pydantic/pydantic/blob/main/LICENSE |
| HTTPX | BSD-3-Clause | https://github.com/encode/httpx/blob/master/LICENSE.md |
| SQLAlchemy | MIT | https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE |
| asyncpg | Apache-2.0 | https://github.com/MagicStack/asyncpg/blob/master/LICENSE |
| Alembic | MIT | https://github.com/sqlalchemy/alembic/blob/main/LICENSE |
| pgvector-python | MIT | https://github.com/pgvector/pgvector-python/blob/master/LICENSE |
| ReportLab | BSD-3-Clause | https://github.com/MrBitBucket/reportlab-mirror/blob/master/LICENSE |
| structlog | MIT OR Apache-2.0 | https://github.com/hynek/structlog/blob/main/LICENSE |
| pytest / pytest-asyncio | MIT / Apache-2.0 | https://github.com/pytest-dev/pytest/blob/main/LICENSE ; https://github.com/pytest-dev/pytest-asyncio/blob/master/LICENSE |
| Ruff / uv | MIT OR Apache-2.0 | https://github.com/astral-sh/ruff/blob/main/LICENSE ; https://github.com/astral-sh/uv/blob/main/LICENSE-MIT |
| mypy | MIT | https://github.com/python/mypy/blob/master/LICENSE |
| pypdf | BSD-3-Clause | https://github.com/py-pdf/pypdf/blob/main/LICENSE |
| types-ReportLab | Apache-2.0 | https://github.com/python/typeshed/blob/main/LICENSE |

Инвентарь составлен по публичным файлам лицензий upstream; наличие записи не заменяет проверку license metadata в установленном окружении и условий для bundled шрифта.
