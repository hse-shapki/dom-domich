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

В репозитории есть устанавливаемый Python-проект и независимые модули аудитории/опросов с тестами. Интеграции MAX/БД ещё не созданы; точное состояние — в [контексте](context/current-state.md).

Локальная проверка: `uv sync --locked`, затем `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/dom_domych`, `uv run pytest`.
