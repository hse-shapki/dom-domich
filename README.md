# dom-domich
Дом Домыч — умный помощник для управления домом в MAX: заявки, инициативы, голосования и коммуникация жильцов.

## Документация

- [AGENTS.md — контекст проекта и единые правила разработки](AGENTS.md)
- [Постоянный контекст для новых задач и агентов](context/README.md)
- [Три персональных пула реализации: Алина, Катерина, Замира](context/implementation-plan.md)
- [Технический проект: архитектура, стек, MAX, агент и данные](docs/engineering/README.md)
- [Последовательность работ и три параллельных трека](docs/engineering/07-workstreams.md)
- [Проверка MVP и фиксация сдаваемой версии](docs/engineering/08-verification-and-release.md)
- [Продуктовая концепция](IDEA.md)
- [Журнал продуктовых решений](docs/open-questions.md)

В репозитории есть Python-проект, независимые модули Замиры и локально проверенные части платформы
Алины: webhook, реестр, inbox/outbox/jobs, callback, онбординг, файлы, rate limits, dev polling и
production Compose/Caddy-конфигурация. Сквозной агент, production repositories K/Z и живой стенд
MAX ещё не подключены; точное состояние — в [контексте](context/current-state.md).

Локальная проверка: `uv sync --locked`, затем `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/dom_domych`, `uv run pytest`.

Для dev-БД: `POSTGRES_PASSWORD=... docker compose -f deploy/compose.dev.yml up -d`, задать
`DATABASE_URL` из `.env.example`, выполнить `uv run alembic upgrade head`. Синтетический seed
запускается только с тестовым именем БД (`dom_domych_test`):
`uv run python -m scripts.seed_demo_house`. Production-конфигурация и безопасный порядок
backup/restore описаны в [runbook Алины](docs/release/alina-operations.md). Docker Compose schema
проверена, но daemon и реальный PostgreSQL 17/pgvector в текущей среде не запустились.
