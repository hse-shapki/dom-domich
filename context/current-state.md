# Проверенное состояние проекта

Проверено 25.09.2026 по рабочему дереву репозитория. Этот файл меняется после реализации задач; старое значение статуса не является вечной истиной.

## Факты на дату проверки

| Область | Состояние | Проверяемое основание |
|---|---|---|
| Продуктовая концепция и журнал решений | Есть документация | `IDEA.md`, `docs/backlog.md`, `docs/open-questions.md` |
| Техническая архитектура, ограничения, треки и приёмка | Есть проектная документация | `docs/engineering/README.md` и восемь документов в той же папке |
| Персональные пулы технических задач | Спланированы; A00–A13/A15–A17 и часть Z реализованы локально или частично | `context/implementation-plan.md`, `tasks-alina.md`, `tasks-katerina.md`, `tasks-zamira.md` |
| Корневые правила для агентов | Есть | `AGENTS.md` |
| Постоянный контекст | Есть | `context/README.md`, `decisions.md`, `product.md`, `engineering.md`, `current-state.md` |
| Чистые доменные правила опросов Z01 | Проверены на unit-уровне | `src/dom_domych/domain/polls/policy.py`, `tests/domain/test_poll_policy.py`: 23 теста |
| Общие контракты A01 / предложение Z00 | Частично: минимальные DTO/ports и tests готовы, K00 не сверена | `src/dom_domych/contracts/`, `src/dom_domych/domain/ports/core.py`, `tests/contracts/test_core.py`, `docs/engineering/11-shared-contracts.md` |
| Синтетический дом Z02 | Проверен как fixture и seed A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`, `scripts/seed_demo_house.py`: 4 fixture-теста |
| AudienceService Z03 | Частично: выбор и история snapshot проверены на fake | `src/dom_domych/domain/audiences/models.py`, `src/dom_domych/application/audiences/service.py`, `tests/domain/test_audience_service.py`; нет PostgreSQL repository/migration |
| PollService Z04 | Частично: поведение и конкуренция проверены на fake | `src/dom_domych/domain/polls/models.py`, `src/dom_domych/application/polls/service.py`, `tests/domain/test_poll_service.py`; нет PostgreSQL repository/migration и MAX callback |
| Callback handler Z05 | Частично: token/actor/revision/expiry проверены на fake | `src/dom_domych/application/polls/callback.py`, `tests/domain/test_poll_callback.py`; A10 MAX transport/action storage существуют, production PollRepository ещё не подключён |
| InitiativeService Z06 | Частично: редакции и замена poll проверены на fake | `src/dom_domych/domain/initiatives/models.py`, `src/dom_domych/application/initiatives/service.py`, `tests/fakes/initiatives.py`, `tests/domain/test_initiative_service.py`; нет K CasePort, PostgreSQL UoW и MAX token revocation |
| Публичные карточки Z07 | Частично: тексты/шкалы проверены unit-тестами | `src/dom_domych/application/cards/builders.py`, `tests/domain/test_public_cards.py`; A DeliveryPort/edit существует, карточки и coalescing ещё не подключены |
| Напоминания и итог инициативы Z08 | Частично: частотный лимит и supported/not_supported проверены на fake | `src/dom_domych/application/initiatives/followup.py`, `tests/fakes/initiative_followup.py`, `tests/domain/test_initiative_followup.py`; A DeliveryPort/jobs существуют, Z/K production wiring ещё нет |
| FileStore и immutable snapshot Z09 | Частично: проверены локально | `src/dom_domych/infrastructure/files/local.py`, `src/dom_domych/domain/documents/snapshot.py`, тесты в `tests/infrastructure/` и `tests/domain/test_document_snapshot.py`; нет PDF worker и PostgreSQL metadata |
| PDF-рендер Z10 | Частично: 4 шаблона проверены локально | `src/dom_domych/infrastructure/documents/renderer.py`, `tests/infrastructure/test_pdf_renderer.py`, 4 синтетических образца в `output/pdf/`; A08/A11 transport есть, durable PDF job и сквозная доставка не подключены |
| DemoExecutor Z11 | Частично: команда и переходы проверены на fake | `src/dom_domych/domain/executor/models.py`, `src/dom_domych/application/executor/service.py`, `tests/fakes/executor.py`, `tests/domain/test_demo_executor.py`; нет PostgreSQL repository/outbox и связи с K RequestService |
| Старт проверки результата Z12 | Частично: done → исходная аудитория/poll проверены на fake | `src/dom_domych/domain/resolution/models.py`, `src/dom_domych/application/resolution/service.py`, `tests/fakes/resolution.py`, `tests/domain/test_resolution_service.py`; нет K CasePort, PostgreSQL UoW и MAX-доставки |
| Итоги проверки результата Z13 | Частично: closed/reopened/unconfirmed проверены на fake | Те же файлы resolution; отдельный K production transition и отмена jobs ещё нужны |
| PDF QA Z15 | Частично: локально просмотрены 4 образца | `docs/release/zamira-pdf-qa.md`; mobile/web MAX и outbox ещё не проверены |
| Материалы Z16 | Частично: локальный handoff и воспроизведение PDF готовы | `docs/release/zamira-handoff.md`, `scripts/generate_zamira_demo_pdfs.py`; сквозной runbook ждёт A/K интеграции |
| Python-проект и зависимости A00 | Проверено локально | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; `uv sync --locked`, Ruff, mypy, 152 tests прошли; удалённый CI ещё не запускался |
| PostgreSQL core A02 | Частично: проверено на локальном PostgreSQL 18 | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`: migration/check и повторный seed; PG17/pgvector Compose не запущен |
| HouseContextPort A05 | Частично: выборка и интеграция с Z AudienceService проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: приглашение, привязка MAX ID, DM `/start`, stopped и выбор дома проверены локально | `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, `tests/infrastructure/test_demo_enrollment.py`; выдача кодов реальным operator и live MAX ещё не подключены |
| MAX Bot API A03 | Частично: документированные методы проверены через MockTransport | `infrastructure/max/client.py`, `tests/infrastructure/test_max_client.py`; upload bytes добавлен в A11, реальный токен/бот не проверены |
| Webhook/inbox A04 | Частично: нормализация и durable insert проверены на PostgreSQL 18 | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`, `tests/infrastructure/test_max_webhook.py`; HTTPS/MAX smoke отсутствует |
| Inbox worker A07 | Частично: lease, recovery и retry проверены на PostgreSQL 18 | `application/jobs/inbox_worker.py`, `infrastructure/postgres/inbox_worker.py`, `tests/infrastructure/test_inbox_worker.py`; отдельный production-процесс и K/Z handlers ещё не подключены |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, DM, карточка/edit и недоступный адресат проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`, `tests/infrastructure/test_delivery_outbox.py`; PDF upload добавлен в A11, реальный MAX и production-процесс ещё не подключены |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency и stale no-op проверены на PostgreSQL 18 | `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`, `tests/infrastructure/test_scheduled_jobs.py`; revision adapter K/Z и production-процесс ещё не подключены |
| MAX poll callbacks A10 | Частично: actor/дом/токен и ACK проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/poll_actions.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_max_poll_callback.py`; Z PollRepository и live MAX ещё не подключены |
| MAX files A11 | Частично: PDF upload, token reuse/retry, безопасное фото, process-local rate limits и coalescing edit реализованы | `infrastructure/max/media.py`, `infrastructure/max/evidence.py`, `infrastructure/max/rate_limit.py`, tests; live MAX mobile/web и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: production Dockerfile, Compose/Caddy, API/outbox process lifecycle и health routes реализованы; Compose schema проверена | `Dockerfile`, `deploy/compose.yml`, `entrypoints/processes.py`, `docs/release/alina-operations.md`; Docker daemon, HTTPS и restart volumes не проверены, inbox/scheduler ждут K/Z wiring |
| Надёжность A13 | Частично: bounded retry/dead-letter/delivery_unknown существовали; добавлены global/dialog/callback rate limits и coalescing pending edit | `infrastructure/max/rate_limit.py`, `infrastructure/postgres/delivery.py`, `tests/infrastructure/test_max_rate_limit.py`, `tests/infrastructure/test_delivery_outbox.py`; live rate-limit и потеря прав MAX не проверены |
| Composition/polling A14 | Частично: dev polling сохраняет batch до marker и запрещён одновременно с webhook | `infrastructure/max/polling.py`, `config.py`, `entrypoints/processes.py`; production K/Z handlers, repositories, общий dispatcher и объединённые migrations отсутствуют |
| Backup/restore A15 | Реализовано, не проверено сквозным restore | `scripts/runtime_backup.py`, `tests/test_runtime_backup.py`, `docs/release/alina-operations.md`; нужен пустой PostgreSQL `*_restore_test` и проверка восстановленного FileStore |
| MAX mobile/web A16 | Не проверено; подготовлен честный протокол | `docs/release/max-mobile-web-matrix.md`; нужен live бот, два клиента и общий G3 runtime |
| Release A17 | Частично: runbook, pinned tags/config placeholders и порядок audit/archive подготовлены | `docs/release/alina-operations.md`, `.env.example`, `Dockerfile`, `deploy/compose.yml`; нельзя фиксировать tag/archive до общего G3, live evidence и согласования формата сдачи |
| Агент, хранение опросов | Не обнаружены в этой ветке | MAX HTTP-клиент частично есть; часть K-пула ведётся в другой ветке |
| Рабочий стенд и внешние проверки | Не подтверждены | Production Compose schema валидна, но Docker daemon недоступен; доступ MAX/модели, HTTPS, mobile/web и цельный runtime не проверялись |

Эти строки описывают только осмотр репозитория. Они не доказывают отсутствие внешнего аккаунта или бота у команды. И наоборот, схема в Markdown не доказывает готовность реализации.

## Следующий шаг по утверждённому плану

Следующий блокирующий шаг — объединить K/Z production repositories, migrations и handlers с A14
composition root. До этого inbox/scheduler нельзя запускать как будто события обработаны. Затем нужны
реальный MAX/LLM доступ, HTTPS smoke, PostgreSQL 17/pgvector restore test и G1–G3/mobile-web
прогоны. Все 152 tests, включая PostgreSQL integrations, прошли на временной локальной
PostgreSQL 18; БД после проверки удалена.

## Как обновлять после задачи

1. Сверить `git status`, файлы и результаты подходящих проверок.
2. Обновить только затронутые строки, указав пути к реализации и точную степень проверки: «частично», «реализовано, не проверено» или «проверено».
3. Синхронизировать раздел «Что уже сделано» в [AGENTS.md](../AGENTS.md) и при необходимости вводную страницу [инженерных документов](../docs/engineering/README.md).
4. Сохранить важный новый выбор в [решениях](decisions.md), а подробности — в соответствующей инженерной спецификации.
5. Включить изменения контекста в коммит выполненной задачи.

Не записывать сюда токены, настоящие данные жильцов или непроверенное утверждение «работает в MAX».
