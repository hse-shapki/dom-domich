# AGENTS.md — правила работы в «Дом Домыч»

Этот файл — стартовый контекст для AI-агентов и разработчиков. Правила применяются ко всему репозиторию. Перед работой прочитай этот файл, затем всю короткую папку [context](context/README.md) и документацию по затрагиваемому модулю. Не начинай реализовывать весь roadmap, если текущая задача касается одного блока.

**Контекст проекта должен сохраняться в файлах.** Окно текущей беседы помогает вести работу, но не является единственным хранилищем решений, статуса и важных ограничений. Перед каждой задачей перечитывай `context/README.md`, `decisions.md`, `current-state.md`, `product.md` и `engineering.md`; для реализации дополнительно открой [план трёх пулов](context/implementation-plan.md) и файл задач выбранного участника. После значимого решения или изменения реализации обновляй относящиеся к нему файлы в том же коммите. После смены задачи или сжатия окна восстанови контекст из этих файлов и проверь актуальное состояние репозитория. Не копируй в них секреты и частные данные.

## 1. Что за проект

**Дом Домыч** — AI-агент дома в мессенджере MAX, проект хакатона по треку «Умный город». Он превращает сообщения жильцов в действия: определяет проблему, затронутую группу, ответственного, необходимые подтверждения и следующий шаг; сопровождает обращение до проверки фактического выполнения.

Интерфейс — **только чат-бот в MAX**, общий чат и личные сообщения. Основной сценарий должен работать в мобильной и веб-версии. Мини-приложение не разрабатываем.

Мы строим агента с инструментами: он получает контекст, вызывает типизированные обработчики и продолжает работу по событиям. Правила доступа, подсчёт голосов, транзакции и допустимые состояния проверяет backend. LLM не является источником истины о выполненных действиях.

Команда из трёх человек ведёт реализацию через AI: **Алина — платформа/MAX**, **Катерина — агент/дела**, **Замира — опросы/документы/результат**. Индивидуальные задачи и порядок интеграции находятся в [плане пулов](context/implementation-plan.md); архитектурные треки — в [плане работ](docs/engineering/07-workstreams.md).

## 2. Актуальные требования и источники

- Прямые актуальные указания пользователя определяют задачу и уточняют проектные решения.
- [Постоянный контекст](context/README.md) хранит краткие решения, смысл продукта, архитектуру и проверенное состояние. При расхождении смотри указанные там первичные источники и фактический код.
- [Техническая документация](docs/engineering/README.md) — основа реализации.
- [Журнал решений](docs/open-questions.md) имеет приоритет над старыми нерешёнными вопросами в начале того же файла.
- [IDEA.md](IDEA.md) и [backlog](docs/backlog.md) содержат исторические решения: не возвращай мини-приложение, голосование по площади или исключение инициатив на основании старого текста.
- Для возможностей MAX используй [документ интеграции](docs/engineering/03-max-integration.md) и указанные в нём официальные источники. Перед изменением интеграции проверяй актуальную документацию; не выдумывай методы и свойства API.

Если при работе обнаружилось расхождение документации и кода, явно зафиксируй его. Код показывает фактическую реализацию, но не делает ошибочное поведение продуктовым требованием.

## 3. Что уже сделано

**Состояние проверено 25.09.2026: A/Z модули и K00–K04 частично реализованы; сквозного приложения и live MAX пока нет.**

| Часть | Статус | Подтверждение |
|---|---|---|
| Концепция, backlog и продуктовые решения | Документация подготовлена | `IDEA.md`, `docs/backlog.md`, `docs/open-questions.md` |
| Python-стек, архитектура, MAX, tools, модель данных, процессы | Спроектировано, не реализовано | `docs/engineering/01-*.md` — `06-*.md` |
| Три трека, персональные пулы задач и критерии приёмки | План подготовлен | `context/implementation-plan.md`, `context/tasks-*.md`, `docs/engineering/07-workstreams.md`, `08-verification-and-release.md` |
| Единые правила разработки | Описаны | Этот файл |
| Общие contracts/ports A01 | Частично, проверено локально | `src/dom_domych/contracts/`, `domain/ports/core.py`, `tests/contracts/test_core.py`; K00 fake handlers сверены с общим контекстом/результатом |
| Постоянный контекст для будущих задач | Описан, поддерживать актуальным | `context/README.md`, `decisions.md`, `current-state.md`, `product.md`, `engineering.md` |
| Доменные правила опросов Z01 | Проверено на unit-уровне | `src/dom_domych/domain/polls/policy.py`, `tests/domain/test_poll_policy.py`; 23 проверки |
| Синтетический дом и fake directory Z02 | Проверено как test fixture и seed A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`, `scripts/seed_demo_house.py`; 4 fixture-проверки |
| AudienceService Z03 | Частично, проверено с fake directory | `src/dom_domych/domain/audiences/models.py`, `application/audiences/service.py`, `tests/domain/test_audience_service.py`; PostgreSQL-репозиторий и миграция ещё нужны |
| PollService Z04 | Частично, проверено с транзакционным fake | `src/dom_domych/domain/polls/models.py`, `application/polls/service.py`, `tests/domain/test_poll_service.py`; нет PostgreSQL concurrency/миграции и доставки MAX |
| Callback handler Z05 | Частично, проверено на нормализованном fake событии | `src/dom_domych/application/polls/callback.py`, `tests/domain/test_poll_callback.py`; A10 transport существует, production PollRepository ещё не подключён |
| InitiativeService Z06 | Частично, проверено с fake CasePort и atomic repository | `src/dom_domych/domain/initiatives/models.py`, `application/initiatives/service.py`, `tests/domain/test_initiative_service.py`; нет K CasePort, PostgreSQL UoW и реального отзыва MAX action tokens |
| Публичные карточки Z07 | Частично, проверено unit-тестами | `src/dom_domych/application/cards/builders.py`, `tests/domain/test_public_cards.py`; DTO не подключён к A DeliveryPort/edit/coalescing |
| Напоминания и итог инициативы Z08 | Частично, проверено с fake rights/outbox | `src/dom_domych/application/initiatives/followup.py`, `tests/fakes/initiative_followup.py`, `tests/domain/test_initiative_followup.py`; нет A DeliveryPort/jobs и K перехода в исполнение |
| FileStore и снимок документа Z09 | Частично, проверено локальными тестами | `src/dom_domych/infrastructure/files/local.py`, `domain/documents/snapshot.py`, `tests/infrastructure/test_local_file_store.py`, `tests/domain/test_document_snapshot.py`; A11 transport для MAX существует, PDF job/metadata не подключены |
| PDF-рендер Z10 | Частично, проверено тестами и просмотром образцов | `src/dom_domych/infrastructure/documents/renderer.py`, `tests/infrastructure/test_pdf_renderer.py`, `output/pdf/`; A08/A11 delivery существует, PDF job и сквозная доставка не подключены |
| DemoExecutor Z11 | Частично, проверено с атомарным fake store | `src/dom_domych/domain/executor/models.py`, `application/executor/service.py`, `tests/fakes/executor.py`, `tests/domain/test_demo_executor.py`; нет PostgreSQL repository/outbox и связи с RequestService |
| Проверка результата Z12 | Частично, проверено с fake case/poll/outbox | `src/dom_domych/domain/resolution/models.py`, `application/resolution/service.py`, `tests/fakes/resolution.py`, `tests/domain/test_resolution_service.py`; нет K CasePort, PostgreSQL UoW и MAX-доставки |
| Итог результата Z13 | Частично, проверено с fake case/poll/outbox | Те же модули resolution: `closed` только после положительного опроса, `reopened` при отрицательном, `resolution_unconfirmed` при нехватке ответов; нет K production transition/jobs |
| PDF QA Z15 | Частично, локальные 4 образца проверены | `docs/release/zamira-pdf-qa.md`; MAX mobile/web и PDF после outbox не проверены |
| Материалы Z16 | Частично, локальный handoff готов | `docs/release/zamira-handoff.md`, `scripts/generate_zamira_demo_pdfs.py`; сквозной runbook ждёт A/K интеграции |
| Python-проект, зависимости и CI A00 | Проверено локально; CI ещё не запускался на GitHub | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; 168 тестов, Ruff и mypy проходят |
| PostgreSQL core A02 | Частично: проверено на локальном PostgreSQL 18, PG17/pgvector Compose не запущен | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`; миграция и повторный seed без дублей |
| HouseContextPort A05 | Частично: чтение реестра и стык с Z проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: приглашение, привязка MAX ID, DM `/start`, stopped и выбор дома проверены локально | `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, `tests/infrastructure/test_demo_enrollment.py`; выдача кодов реальным operator и live MAX ещё не подключены |
| MAX Bot API A03 | Частично: HTTPX MockTransport проверен, live-доступа нет | `infrastructure/max/client.py`, `tests/infrastructure/test_max_client.py`; загрузка bytes добавлена в A11, smoke в MAX ещё нужен |
| Webhook/inbox A04 | Частично: text/callback/attachment refs/deletion/lifecycle/membership/admin permissions и unknown Update проверены через ASGITransport + PostgreSQL 18; внешнего HTTPS/MAX нет | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`; обработка через A07 подключается позже |
| Inbox worker A07 | Частично: lease, recovery и retry проверены на PostgreSQL 18 | `application/jobs/inbox_worker.py`, `infrastructure/postgres/inbox_worker.py`, `tests/infrastructure/test_inbox_worker.py`; отдельный production-процесс и K/Z handlers ещё не подключены |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, DM, карточка/edit и недоступный адресат проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`, `tests/infrastructure/test_delivery_outbox.py`; PDF upload добавлен в A11, реальный MAX и production-процесс ещё не подключены |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency и stale no-op проверены на PostgreSQL 18 | `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`, `tests/infrastructure/test_scheduled_jobs.py`; revision adapter K/Z и production-процесс ещё не подключены |
| MAX poll callbacks A10 | Частично: actor/дом/токен и ACK проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/poll_actions.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_max_poll_callback.py`; Z PollRepository и live MAX ещё не подключены |
| MAX files A11 | Частично: PDF upload, token reuse/retry, безопасное фото, локальные rate limits и coalescing edit проверены unit/MockTransport; PostgreSQL-сценарии требуют test DB | `infrastructure/max/media.py`, `infrastructure/max/evidence.py`, `infrastructure/max/rate_limit.py`, tests; live MAX mobile/web и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: Dockerfile, production Compose/Caddy, API/outbox/retention lifecycle и health routes реализованы; Compose schema проверена | `Dockerfile`, `deploy/compose.yml`, `entrypoints/processes.py`; daemon/HTTPS/restart volumes не проверены, inbox/scheduler ждут K/Z |
| Надёжность A13 | Частично: bounded retry, dead-letter, `delivery_unknown`, rate limits, coalescing и lease heartbeat проверены локально | `application/notifications/worker.py`, `application/jobs/scheduler.py`, infrastructure queue tests; live потеря прав/rate limits не проверены |
| Composition/polling A14 | Частично: polling commit-before-marker, взаимоисключение ingress modes, multi-handler dispatcher и revision router реализованы | `infrastructure/max/polling.py`, `application/jobs/inbox_worker.py`, `application/jobs/scheduler.py`; K/Z handlers/repositories/migrations и общий G3 runtime отсутствуют |
| Backup/restore A15 | Проверено локально на PostgreSQL 18 и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, `tests/infrastructure/test_retention_maintenance.py`; восстановлены Alembic head, 2 дома/20 проживаний и PDF hash; container restart ещё не проверен |
| MAX matrix A16 | Не проверено; подготовлен протокол без фиктивных отметок | `docs/release/max-mobile-web-matrix.md`; нужен live бот, mobile/web и общий runtime |
| Release A17 | Частично: runbook, env placeholders, secret/history audit, transitive license inventory и evidence/archive tool подготовлены | `scripts/release_audit.py`, `docs/release/platform-operations.md`; история чиста, но лицензия собственного проекта не выбрана; tag/digests допустимы только после G3 |
| K00: стыки агента, дел и знаний | Проверено на contract/fake уровне; production порты ещё не связаны | `src/dom_domych/agent/contracts.py`, `fakes.py`, `tool_handlers.py`, `tests/agent/test_k00_contracts.py` |
| K01: eval dataset | Проверен формат и покрытие; модель не запускалась | `evals/k01_cases.jsonl`, `evals/README.md`, `tests/agent/test_k01_dataset.py` |
| K02: inference | Частично: HTTPX adapter/fake/timeout/retry проверены; 8 GiB Mac не выдержал live probe | `src/dom_domych/agent/llm.py`, `infrastructure/llm/llama_server.py`, `tests/agent/test_k02_llama_server.py`, `docs/engineering/11-track-k-inference-probe.md` |
| K03: agent runtime | Частично: allowlist/schema/capability/budget и общий ToolResult проверены fake tests; production handlers не подключены | `src/dom_domych/agent/runtime.py`, `tests/agent/test_k03_runtime.py` |
| K04: continuation | Частично: PostgreSQL runs/pending/tool audit и fresh context проверены локально; inbox не подключён | `src/dom_domych/agent/continuation.py`, `infrastructure/postgres/agent_runs.py`, `tests/infrastructure/test_k04_agent_runs.py` |
| K05: knowledge | Частично: разрешённый HTTPS ingestion, review, русская FTS и scoped rules проверены на PostgreSQL 16; pgvector branch/live embeddings не проверены | `application/knowledge/service.py`, `infrastructure/postgres/knowledge.py`, `infrastructure/llm/embeddings.py`, `tests/infrastructure/test_k05_knowledge.py` |
| K06: triage | Частично: пять маршрутов, несколько тем, срочный guard и ответ только с проверенным source проверены fake tests; live eval/inbox wiring отсутствуют | `src/dom_domych/agent/triage.py`, `tests/agent/test_k06_triage.py` |
| K07: case retrieval | Частично: house/location/object/30-day closed filters и FTS проверены на PostgreSQL 16; pgvector branch не проверена | `application/cases/candidates.py`, `infrastructure/postgres/case_candidates.py`, `tests/infrastructure/test_k07_candidates.py` |
| Хранение опросов и production-интеграция агента | Не реализованы | A/Z core и K fake runtime есть; K/Z ORM интеграций ещё нет |
| Тесты и проверенный стенд | Частично | A/Z tests ранее проходили с PostgreSQL 18; совместные проверки после слияния указаны в `context/current-state.md`; PG17/pgvector, реальный MAX и цельный стенд не проверены |

Наличие схем, таблиц, примеров и списка технологий не означает, что функция работает. Доступ к токену MAX, серверу и inference не считается полученным без фактической проверки.

### Как поддерживать статус

После существенной реализации обновляй эту таблицу в той же задаче: укажи конкретный модуль, состояние и путь к коду/проверке. Используй статусы «не реализовано», «частично», «реализовано, не проверено», «проверено»; для документов — «спроектировано».

Не отмечай модуль готовым по одному scaffold или успешному import. Указывай ограничения и фактически выполненную проверку. Если реализация началась, одновременно убирай устаревшие утверждения «кода ещё нет» из README и технической навигации. Не превращай этот файл в подробный журнал каждого коммита.

## 4. Что нужно реализовать

1. **Основа:** Python-проект, конфигурация, БД, миграции, фоновые задачи, тестовый дом и реестр жителей.
2. **MAX:** webhook, сообщения, callbacks, загрузка файлов, онбординг и личные уведомления.
3. **Агент:** авария / обычная проблема / вопрос / инициатива / разговор; уточнения, поиск знаний, маршрутизация, tools и продолжение по событиям.
4. **Проблемы:** дедупликация, подтверждения, доказательства и подготовка обращения.
5. **Инициативы:** карточка, голосование, шкалы участия/поддержки, напоминания.
6. **Документы:** PDF обращения, протокола позиции жителей, реестра уведомлений и черновика жалобы.
7. **Исполнение:** тестовый адаптер исполнителя, регистрация, статусы, опрос после выполнения, закрытие или возврат.
8. **Аварии:** срочная ветка, применимые проверенные сроки, таймеры и дальнейшие действия при просрочке.
9. **Приёмка:** сквозные процессы, сбои, agent evals, MAX mobile/web и фиксированная версия сдачи.

Расширения после работоспособного полного цикла: память дома, анализ фото, голосовые сообщения, повторяемость проблем, сводки и ранние признаки аварии. Их реализация зависит от текущей задачи и готовности общей системы. Не добавляй мини-приложение, платежи, индекс дома и модерацию разговоров из собственной инициативы.

### Продуктовые инварианты

- Один подтверждённый житель — один голос; площадь квартиры на вес не влияет.
- Квартира связана с домом, подъездом, этажом и инженерными стояками; не угадывай стояк по номеру квартиры.
- Адресат определяется по реестру и scope проблемы; групповой чат не раскрывает персональные ответы.
- Повтор сообщения не равен новому подтверждению; молчание не считается «нет».
- Порог считается от зафиксированной категории, а не только от успешно уведомлённых.
- Обычная проблема: порог либо ожидание до пяти часов, затем запрос доказательств при недостатке поддержки.
- Авария не ждёт коллективного порога; применимый срок отсчитывается от соответствующего регистрационного события.
- «Исполнитель отметил выполнение» не означает «жители подтвердили результат».
- Неутверждённые пороги — версия demo policy, а не выдуманная нормативная норма.
- Реестр, государственные интеграции и внешний исполнитель в MVP явно моделируются. Протокол позиции жителей не выдаётся за официальный протокол ОСС.

## 5. Принятый стек

- Python 3.13, `asyncio`, uv; один пакет `src/dom_domych`.
- FastAPI + Uvicorn; Pydantic 2 для contracts и tool schemas.
- HTTPX AsyncClient для официального Bot API MAX и inference.
- PostgreSQL 17, SQLAlchemy 2 async + asyncpg, Alembic; pgvector и full-text search.
- Собственный небольшой agent runtime; llama.cpp и открытые модели через `LlmPort`. Кандидаты моделей указаны в [стеке](docs/engineering/01-scope-and-stack.md), принимаются после evals.
- PostgreSQL inbox/outbox/jobs; persistent FileStore; ReportLab/Platypus для PDF.
- structlog, pytest + pytest-asyncio, Ruff, mypy; Docker Compose и Caddy.

Не добавляй заменяющий framework, брокер или ORM ради привычки. Новая зависимость должна решать конкретную задачу; проверь лицензию и обнови документацию/lockfile. Точные версии фиксируются при создании окружения. Закрытые библиотеки, недокументированные сторонние API и секреты в Git запрещены условиями проекта.

## 6. Единый стиль Python

### Язык и именование

- Идентификаторы, имена файлов, модулей, таблиц и структурированные коды событий/ошибок — на английском.
- Объяснения в документации, комментарии, docstrings и тексты для жителей — на русском. Названия API и цитаты источников сохраняй в оригинале.
- `snake_case` для функций, переменных, модулей и полей; `PascalCase` для классов; `UPPER_SNAKE_CASE` для констант.
- Внешние поля MAX сохраняют формат API через явный mapping/alias. Не меняй опубликованные tool names и event identifiers ради внутреннего стиля Python.
- Имена отражают предметную область: `case_id`, `audience_id`, `resident_id`. Избегай неопределённых `manager`, `helper`, `data` и общей свалки `utils.py`.

### Формат и типизация

- Отступ — 4 пробела, длина строки — 100, двойные кавычки; итоговое форматирование определяет Ruff. Эти настройки зафиксировать в `pyproject.toml` на S0.
- Импорты группируются: стандартная библиотека, сторонние пакеты, `dom_domych`; внутри проекта используй абсолютные импорты. Без `import *`.
- Все функции и методы имеют аннотации параметров и результата. Используй `list[T]`, `dict[K, V]`, `T | None`; не распространяй `Any` из внешнего JSON по приложению.
- Для внешних DTO — Pydantic, для домена — dataclasses/типы значений, для заменяемых зависимостей — `Protocol`. ORM-модель не является DTO.
- Не используй изменяемые значения по умолчанию. Не скрывай типовые проблемы массовыми `type: ignore` или отключением lint; исключение должно быть локальным и объяснимым.
- Функция выполняет одну понятную операцию. Предпочитай ранний выход и явные условия глубокой вложенности; не создавай абстракцию без реального второго сценария использования.
- Docstrings нужны публичным contracts и нетривиальным правилам: что делает операция, её ограничения и эффекты. Комментарий объясняет причину, не пересказывает строку кода.

### Ошибки и логи

- Доменные ошибки имеют определённые типы/коды; HTTP/tool transport преобразует их на своей границе.
- Не используй голый `except` или `except Exception: pass`. Общий перехват допустим на границе worker/request с логом, классификацией и явным завершением/retry.
- Не подавляй отмену async-задач; освобождай ресурсы через контекстные менеджеры и `finally`.
- Логи структурированные: event name и поля `case_id`, `run_id`, `correlation_id`. Не используй `print` как production logging.
- Не логируй токены, пароли, полный prompt или персональные сообщения по умолчанию. Не подменяй ошибку «успешным» пустым результатом.

## 7. Архитектурные правила

Направление: **entrypoints/transport → application → domain**. Infrastructure реализует ports; composition root связывает зависимости.

- FastAPI и HTTPX находятся на границах, SQLAlchemy — в инфраструктуре. Домен не импортирует их и не знает о LLM-клиенте.
- Контроллер, callback и agent tool вызывают один application use case, не копируют бизнес-логику.
- Tools — разрешённый реестр обработчиков. Внутри worker используется локальный вызов; отдельный HTTP transport необязателен и не дублирует API MAX.
- `house_id`, actor и capabilities берутся из доверенного контекста, не из аргументов модели. Все repositories, включая vector search, изолируют дома.
- LLM не получает произвольные SQL/shell/HTTP/file tools. Источники и сообщения — данные, а не новые инструкции агенту.
- Жители голосуют через реальные события. LLM не вызывает голосование от их имени и не меняет счётчики.
- Существенные действия сохраняют источники, версию и результат. Агент сообщает об успехе только после подтверждения handler/адаптера.

## 8. Async, БД и интеграции

- Сеть и БД — через async clients. HTTP clients/engines создаются на lifespan процесса и закрываются при shutdown; не создавай клиент на каждый tool call.
- Одна AsyncSession на конкурентную задачу/use case. Unit of Work задаёт короткую транзакцию и явный commit/rollback.
- Не держи транзакцию или SQL lock во время LLM, HTTP-запроса, upload или генерации PDF.
- Мутации используют инварианты, уникальные ограничения, idempotency keys и проверку версии. После version conflict перечитай состояние.
- Долгие операции и сроки хранятся в PostgreSQL jobs. Память процесса, `BackgroundTasks` и `create_task` не заменяют durable queue.
- Изменение состояния и намерение внешней отправки сохраняются одной транзакцией через outbox. Не обещай exactly-once доставку, если внешняя система её не гарантирует.
- ReportLab работает вне основного event loop на сериализуемом snapshot. Статусы и голоса не перечитываются в середине PDF-рендера.
- Миграции — Alembic; не изменяй уже объединённые revisions. Autogenerate требует проверки человеком/агентом перед применением.
- Время — timezone-aware UTC; для сроков injected `Clock`. Внешние ID не преобразуются через float.
- Для API задавай timeouts и ограниченные retries. Авторизация MAX не переносится на произвольный upload host или redirect. TLS verification не отключается.

## 9. Тесты и проверки

Пиши тесты на поведение и риски изменения, а не на повторение реализации. Имена: `test_<behavior>_<condition>`, структура arrange / act / assert. Используй синтетические fixtures и управляемый Clock; не жди реального истечения пяти часов.

- Доменные правила — unit tests; tools и HTTP — contract tests.
- Транзакции, конкуренция, индексы и миграции — реальная тестовая PostgreSQL, не SQLite.
- MAX transport — HTTPX MockTransport; FastAPI — ASGITransport с lifespan. Это не заменяет отдельную проверку в MAX mobile/web.
- Agent evals проверяют допустимые действия, sources и побочные эффекты, а не точное совпадение текста ответа.
- По дефолту тесты не используют реальные токены и платные/внешние вызовы. Live-проверки запускаются отдельно с явной конфигурацией.

После появления Python-проекта базовые команды:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src/dom_domych
uv run pytest
```

Команды работают локально после A00; GitHub workflow ещё не проверен удалённым прогоном. Для документационных изменений достаточно проверки ссылок, согласованности и `git diff --check`; не создавай тесты приложения ради Markdown-правки.

## 10. Рабочий процесс и завершение задачи

Перед новой задачей реализации спроси, **кто из Алины, Катерины и Замиры сейчас ведёт соответствующий пул**, если человек или task ID ещё не указан в запросе/текущем контексте. Затем открой его файл из [плана](context/implementation-plan.md), сверь зависимости и выполняй порученный task. Если участник или ID уже назван, повторно не спрашивай; для документационной задачи без роли вопрос не нужен. Переназначение задачи между пулами сначала зафиксируй в плане.

1. Проверь `git status`, фактические файлы и локальные инструкции; не затирай чужие незакоммиченные изменения.
2. Перечитай всю папку `context/`, начиная с её README, затем задачи выбранного пула и относящуюся к задаче спецификацию. Полные правила находятся в `docs/engineering`, здесь — общий стандарт. Не полагайся только на память из окна беседы.
3. Выполни текущую задачу в её объёме. Не создавай пустые модули всего roadmap для имитации прогресса.
4. При параллельной работе соблюдай границы пулов A/K/Z; согласовывай shared contracts и миграции перед объединением, не плодя несовместимые версии. Пока соседний модуль не готов, используй согласованный fake port, а не редактируй чужой модуль.
5. Запусти подходящие проверки. Если проверка недоступна, укажи причину; не представляй её как пройденную.
6. Обнови затронутую документацию и контекстные файлы: новое решение — в `context/decisions.md`, изменившуюся готовность — в `context/current-state.md` и таблице выше, продуктовые/технические изменения — в соответствующем файле `context/` со ссылкой на подробную спецификацию. Сохраняй только подтверждённые факты.
7. После каждой завершённой задачи создай отдельный Git-коммит со всеми и только относящимися к этой задаче изменениями. Перед коммитом проверь staged diff и убедись, что в коммит не попали прежние незакоммиченные изменения пользователя.
8. Не добавляй `Co-authored-by`, `Co-Authored-By`, `Signed-off-by` или другие trailers, упоминания и кредиты AI/ИИ-агента в сообщение коммита. Не добавляй автора или соавтора от имени модели в текст коммита. Используй настроенную identity пользователя; не меняй Git identity конфигурацию.
9. Не переписывай существующую историю коммитов: не amend, не rebase и не reset, если пользователь отдельно этого не попросил. Не обходи hooks и подпись коммита. Если commit hook или настроенная подпись блокирует коммит, сохрани изменения и объясни препятствие.
10. В результате кратко сообщи, что изменено, какие проверки выполнены и хеш созданного коммита. Если коммит не удалось создать, честно укажи почему.

В сдаваемой версии фиксируются код, prompts, модель, правила и конфигурация. После дедлайна не передвигай submitted tag и не подменяй переданную версию; новые изменения ведутся отдельно.
