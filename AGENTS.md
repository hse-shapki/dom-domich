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

**Состояние на 30.09.2026: A-MVP-1 и локальная часть Z-MVP-1 объединены; A-MVP-2 прошла 308 тестов на чистой PostgreSQL 18/pgvector, а предыдущий clean PG17/pgvector прогон дал 303 теста, Ruff, format, mypy, двойной runtime seed и Alembic check. Единый polling Compose подтвердил `/me`, Ollama `qwen3:4b`, normal MAX message и redacted read-back по durable inbox → agent/tools → sent outbox. Допустимый live голос, Z PDF в mobile/web и цельный MAX/LLM G3 ещё не подтверждены. Подробности — в [current-state](context/current-state.md).**

| Часть | Статус | Подтверждение |
|---|---|---|
| Концепция, backlog и продуктовые решения | Документация подготовлена | `IDEA.md`, `docs/backlog.md`, `docs/open-questions.md` |
| Python-стек, архитектура, MAX, tools, модель данных, процессы | Спроектировано; значительная часть реализована частично | `docs/engineering/01-*.md` — `06-*.md`, `src/dom_domych/` |
| Три трека, персональные пулы задач и критерии приёмки | План подготовлен | `context/implementation-plan.md`, `context/tasks-*.md`, `docs/engineering/07-workstreams.md`, `08-verification-and-release.md` |
| Единые правила разработки | Описаны | Этот файл |
| Общие contracts/ports A01 | Частично, проверено локально | `src/dom_domych/contracts/`, `domain/ports/core.py`, `tests/contracts/test_core.py`; K00 fake handlers сверены с общим контекстом/результатом |
| Постоянный контекст для будущих задач | Описан, поддерживать актуальным | `context/README.md`, `decisions.md`, `current-state.md`, `product.md`, `engineering.md` |
| Доменные правила опросов Z01 | Проверено на unit-уровне | `src/dom_domych/domain/polls/policy.py`, `tests/domain/test_poll_policy.py`; 23 проверки |
| Синтетический дом и fake directory Z02 | Проверено как test fixture и seed A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`, `scripts/seed_demo_house.py`; 4 fixture-проверки |
| AudienceService Z03 | Частично: PostgreSQL snapshot/revision/idempotency и конкурентный successor проверены на локальной PostgreSQL 17; K problem/initiative/emergency route подключён и проверен на PostgreSQL 17 | `application/audiences/service.py`, `infrastructure/postgres/audiences.py`, `migrations/versions/63a9d1e4bc02_z03_audiences.py`, `tests/infrastructure/test_z03_audiences_postgres.py` |
| PollService Z04 | Частично: opening атомарно сохраняет poll/job и личное приглашение каждому eligible с bound callback-кнопками; replay не дублирует, revise отменяет pending старой редакции; проверено PostgreSQL 17 29.09.2026 | `infrastructure/postgres/polls.py`, `poll_notifications.py`, `tests/infrastructure/test_z04_polls_postgres.py`, `test_z06_initiatives_postgres.py`; live MAX не проверен |
| Callback handler Z05 | Частично: голос, личный feedback и edit карточки сохраняются атомарно; actor/дом/frozen audience, повторы, смена выбора и сроки проверены PostgreSQL/MockTransport | `application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`; live отказ вне аудитории подтверждён, допустимый голос не проверен |
| InitiativeService Z06 | Частично: новая редакция атомарно обновляет case text/version, отменяет старый poll/tokens/pending invitations, открывает новые голоса и выпускает durable событие обновления карточки; replay/concurrency/карточка проверены на PostgreSQL 17 29.09.2026 | `application/initiatives/`, `infrastructure/postgres/initiatives.py`, `tests/infrastructure/test_z06_initiatives_postgres.py`; live MAX не проверен |
| Публичные карточки Z07 | Частично: публикация и атомарный edit после callback, удаление кнопок при финализации проверены локально; live доставка карточки и transport edit того же group message ID подтверждены, доменный edit не проверен | `application/cards/production.py`, `application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`, `test_z07_cards_outbox.py` |
| Напоминания и итог инициативы Z08 | Частично: два durable reminder job, права/частота/outbox и supported/not_supported связаны с case request_ready/not_supported; поддержанная инициатива прошла approval/submit/исполнение в локальном G3 | `infrastructure/postgres/initiative_followup.py`, `application/resolution/production.py`, `test_z08_followup_postgres.py`, `test_g3_runtime.py`; live MAX не проверен |
| FileStore и снимок документа Z09 | Частично: registration → immutable appeal snapshot в одной транзакции; replay с изменившимся Clock сохраняет исходные bytes/hash, проверено на PostgreSQL 17 29.09.2026 | `application/documents/production.py`, `infrastructure/postgres/documents.py`, `tests/infrastructure/test_g3_runtime.py`, `test_z09_documents_postgres.py`; position PDF автоматически после initiative decision; приватный notice register требует отдельной capability; complaint PDF из K deadline draft. Проверены источники, ACL, replay и worker трёх видов в `test_z08_followup_postgres.py`; live MAX не проверен |
| PDF-рендер Z10 | Частично: 4 шаблона, lease/recovery и PostgreSQL → process pool → FileStore → приватный outbox → MAX upload/DM проверены локально | `application/documents/worker.py`, `tests/infrastructure/test_z09_documents_postgres.py`, `test_z10_max_pdf_pipeline.py`; Z файлы в mobile/web не открывались |
| DemoExecutor Z11 | Частично: PostgreSQL idempotency/конкуренция, approved draft, права, события/outbox и K регистрацию проверены локально; K/A process root подключён | `infrastructure/postgres/demo_executor.py`, `application/executor/production.py`, `application/resolution/production.py`, `entrypoints/processes.py`, `tests/infrastructure/test_z11_demo_executor_postgres.py`; локальный `entrypoints/zamira_operator.py` проверен: register/status replay и запрет live-дома; live MAX ещё не проверен |
| Проверка результата Z12 | Частично: done запускает личный опрос исходной проблемы/действующей редакции инициативы/frozen emergency audience; авария без начального poll и все три outcome проверены на PostgreSQL 17 29.09.2026 | `infrastructure/postgres/original_audience.py`, `resolution.py`, `tests/infrastructure/test_z12_resolution_postgres.py`, `test_z06_initiatives_postgres.py`; live MAX не проверен |
| Итог результата Z13 | Частично: три outcome, case event, отмена будущих jobs, resolution.rejected и late done/stale version no-op проверены PostgreSQL 17 29.09.2026 | `application/resolution/production.py`, `infrastructure/postgres/resolution.py`, `tests/infrastructure/test_z12_resolution_postgres.py`, `test_g3_runtime.py`; live MAX не проверен |
| Сквозная проверка Z14 | Частично: 9 production PostgreSQL 17 сценариев problem/initiative/emergency → request/PDF/executor → три исхода и отдельный problem → MAX callback/card → request/PDF → closed/reopened MockTransport путь | `tests/infrastructure/test_g3_runtime.py`, `test_g3_runtime_callback.py`; цельный live MAX/LLM G3 отсутствует |
| PDF QA Z15 | Частично: 29.09.2026 заново сгенерированы/просмотрены 4 образца (7 страниц) и 4 production PostgreSQL/FileStore документа (6 страниц); embedded fonts, snapshot/hash/поля/приватность сверены | `docs/release/zamira-pdf-qa.md`, `output/pdf/qa-2026-09-29/manifest.json`; MAX mobile/web не проверены |
| Материалы Z16 | Частично: handoff, 9 G3 сценариев, четыре PDF/manifest, ручной сценарий двух исходов и live PDF smoke подготовлены | `docs/release/zamira-handoff.md`, `zamira-manual-demo.md`, `zamira-live-pdf-smoke.md`; MAX mobile/web evidence отсутствуют |
| Python-проект, зависимости и CI A00 | Проверено локально; предыдущий remote набор — GitHub Actions #50 | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; ветка A-MVP-2 прошла 308 тестов на чистой PostgreSQL 18/pgvector, предыдущий clean PG17 прогон — 303 теста; migration/check, двойной seed, Ruff и mypy прошли; CI ожидается |
| PostgreSQL core A02 | Проверено локально на PostgreSQL 17 + pgvector 0.8.1 | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`, `src/dom_domych/demo/house.py`; clean migration/check до Z head и повторный runtime seed пройдены в A-MVP-1 |
| HouseContextPort A05 | Частично: чтение реестра и стык с Z проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: operator CLI, приглашение, signed int64 group chat ID, привязка MAX ID/чата, stopped и выбор дома проверены на PostgreSQL; личное сообщение неподтверждённого жителя теперь получает подсказку `/start` по локальному MockTransport-тесту; прежние live `/start <код>` и привязка группы подтверждены | `entrypoints/demo_operator.py`, `infrastructure/max/onboarding.py`, `tests/infrastructure/test_demo_enrollment.py`; новый fallback в live MAX, mobile и несколько домов ещё не проверены |
| MAX Bot API A03 | Частично: HTTPX MockTransport, live `/me`, личная/групповая отправка, `POST /answers`, PDF upload и redacted `GET /messages/{messageId}` проверены 29–30.09.2026; MAX TLS использует объединённые Mozilla/Russian roots без ambient proxy | `infrastructure/max/client.py`, `scripts/max_operations.py`, `infrastructure/max/tls.py`, `tests/infrastructure/test_max_client.py`, `test_max_tls.py`; mobile ещё не проверен |
| Webhook/inbox A04 | Частично: text/callback/attachment refs/deletion/lifecycle/membership/admin permissions и unknown Update проверены через ASGITransport + PostgreSQL; live polling принял `bot_started` и `message_created` | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`; публичный HTTPS webhook и прочие live-типы ещё не проверены |
| Inbox worker A07 | Частично: lease/recovery/retry и production loop с K/Z handlers проверены локально | `entrypoints/processes.py`, `application/jobs/inbox_worker.py`, K/Z tests; live MAX не проверен |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, signed group ID, DM, карточка/edit, недоступный адресат и отдельный process loop проверены на PostgreSQL 17 + MockTransport; durable личная, групповая, карточка с кнопками, PDF и edit того же group message ID реально прошли MAX | `entrypoints/processes.py`, `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`; визуальная mobile/web проверка и доменный edit Z-карточки ещё нужны |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency, stale no-op и K/Z handlers в production loop проверены локально | `entrypoints/processes.py`, `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`; live runtime не проверен |
| MAX poll callbacks A10 | Частично: actor/дом/токен, outcome-specific notification и Z PollRepository проверены на PostgreSQL/MockTransport; live группа передала callback, сервер корректно не записал голос жителя вне frozen audience, прямой notification принят MAX | `infrastructure/postgres/poll_actions.py`, `application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`; live допустимый голос и edit ещё не проверены |
| MAX files A11 | Частично: synthetic PDF реально прошёл FileStore → upload → token → bounded retry → приватную доставку и виден в web MAX; безопасное фото и K evidence linkage проверены локально на PG16.13, rate limits/coalescing — отдельными тестами | `infrastructure/max/media.py`, `infrastructure/max/tls.py`, `application/agent/resident_production.py`, `tests/infrastructure/test_z_mvp1_resident_actions.py`; открытие файла, mobile, реальный документ Z и live фото ещё нужны |
| Deploy/runtime A12 | Частично: clean Compose profile `polling` последовательно запускает PG17/pgvector, migrate, runtime demo seed, polling/inbox/scheduler/outbox/documents/maintenance и redacted preflight; `/me` и `qwen3:4b` отвечают из того же stand | `deploy/compose.yml`, `entrypoints/preflight.py`, `docs/release/platform-operations.md`; host Ollama обязателен, публичный DNS/TLS и mobile/web не проверены |
| Надёжность A13 | Частично: bounded retry, dead-letter, `delivery_unknown`, rate limits, coalescing и lease heartbeat проверены локально | `application/notifications/worker.py`, `application/jobs/scheduler.py`, infrastructure queue tests; live потеря прав/rate limits не проверены |
| Composition/polling A14 | Частично: локальная production-цепь problem → request → PDF/FileStore/binding → demo registration/done → resolution poll → closed проверена; общий Compose live провёл normal MAX group message через durable inbox, agent/tools и sent outbox | `tests/infrastructure/test_g3_runtime.py`, `docs/release/a-mvp-1-evidence.md`; следующий `problem.detected` не принят downstream Z-MVP-1 handler, поэтому это ещё не live G3 |
| Backup/restore A15 | Проверено локально на PostgreSQL 17.8/pgvector и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, retention tests; восстановлены Z head `0a7b6c5d4e3f`, vector, 40 public tables и 5 file hashes; PostgreSQL/FileStore named volumes пережили Compose restart |
| MAX matrix A16 | Не проверено; подготовлен протокол без фиктивных отметок | `docs/release/max-mobile-web-matrix.md`; нужен live бот, mobile/web и общий runtime |
| Release A17 | Частично: runbook, env placeholders, secret/history audit, transitive license inventory и evidence/archive tool подготовлены; CI Actions закреплены по SHA актуальных релизов | `scripts/release_audit.py`, `.github/workflows/python.yml`, `docs/release/platform-operations.md`; история чиста, но лицензия собственного проекта не выбрана; tag/digests допустимы только после G3 |
| K00: стыки агента, дел и знаний | Проверено локально: единый реестр девяти K tools связан с runtime и production K services | `src/dom_domych/agent/contracts.py`, `tool_handlers.py`, `tools.py`, `application/agent/composition.py`, K00/K03/K11 tests |
| K01: eval dataset | Проверен формат и покрытие; модель не запускалась | `evals/k01_cases.jsonl`, `evals/README.md`, `tests/agent/test_k01_dataset.py` |
| K02: inference | Частично: OpenAI-compatible и нативный Ollama adapters, fake/timeout/retry проверены; локальный `qwen3:4b` выполнил структурированные tool calls в production-подобном PostgreSQL-прогоне, но evals и метрики не пройдены | `src/dom_domych/agent/llm.py`, `infrastructure/llm/llama_server.py`, `infrastructure/llm/ollama.py`, K02 tests, `docs/engineering/11-track-k-inference-probe.md` |
| K03: agent runtime | Частично: allowlist/schema/capability/budget и девять K tools собраны с production K services; backend подставляет доверенные source/idempotency IDs и отклоняет floor без verified entrance до handler; локальный inference прошёл `case.search` → `case.create` → reply outbox | `src/dom_domych/agent/runtime.py`, `agent/contracts.py`, `agent/tools.py`, `application/agent/composition.py`, K03/K14 tests; полный MAX/G3 и evals ещё не проверены |
| K04: continuation | Частично: PostgreSQL runs/pending/tool audit, fresh context и K dispatcher/scheduler composition проверены локально; production process подключён | `src/dom_domych/agent/continuation.py`, `application/agent/composition.py`, K04/K14 tests; live inference не проверен |
| K05: knowledge | Частично: разрешённый HTTPS ingestion, review, русская FTS и scoped rules проверены на PostgreSQL 18; PG17/pgvector/live embeddings не проверены | `application/knowledge/service.py`, `infrastructure/postgres/knowledge.py`, `infrastructure/llm/embeddings.py`, `tests/infrastructure/test_k05_knowledge.py` |
| K06: triage | Частично: пять маршрутов, несколько тем и срочный guard подключены к MAX inbox; вопрос отвечает из reviewed source либо просит уточнить, личное приветствие получает ответ без mutation tools; validation отказ tool теперь даёт жителю явное уточнение места вместо молчания/dead-letter; actor/дом берутся из подтверждённого совершеннолетнего проживания; live eval отсутствует | `agent/triage.py`, `application/agent/messages.py`, `infrastructure/postgres/message_agent.py`, `tests/agent/test_z_mvp1_message_actions.py` |
| K07: case retrieval | Частично: house/location/object/30-day closed filters и FTS проверены на PostgreSQL 18; PG17/pgvector branch не проверена | `application/cases/candidates.py`, `infrastructure/postgres/case_candidates.py`, `tests/infrastructure/test_k07_candidates.py` |
| K08: CaseService | Частично: create/attach/recurrence, events, idempotency, конкурентный dedupe и Z06 case/author adapter проверены на PostgreSQL 18; Z transactional repository и K problem/initiative route подключены и проверены локально на PostgreSQL 17 | `application/cases/service.py`, `infrastructure/postgres/case_writer.py`, `initiative_cases.py`, K08/Z06 tests |
| K09: обычная проблема | Частично: production route сохраняет frozen audience/poll/deadline/case/card-outbox; trusted outcome переводит дело в request_ready либо needs_evidence. Личное фото через MAX ingress привязывается к делу и FileStore; отправитель отдельно оценивает релевантность с source ref, без vision и автоматического перехода к обращению | `application/cases/evidence.py`, `application/agent/resident_production.py`, `infrastructure/max/evidence.py`, `tests/infrastructure/test_z_mvp1_resident_actions.py`; локальный PG16, live MAX-фото не проверено |
| K10: RequestService | Частично: reviewed rule и ответственный проверяются до draft; автор получает данные для просмотра, явно согласует версию и отдельно отправляет demo executor из личного чата. Submit требует того же approval actor; production appeal snapshot/binding проверены локально | `application/requests/service.py`, `application/agent/resident_production.py`, K10/Z-MVP-1 tests; live MAX delivery не проверено |
| K11: emergency | Частично: typed agent tool не ждёт poll; durable `emergency.detected` фиксирует исходную аудиторию для PDF/result, evidence остаётся личным | emergency application/runtime modules и tests; live MAX не проверен |
| K12: deadline | Частично: job ставится при доверенной регистрации; due создаёт review-only followup с повторной проверкой версии/статуса, K revision/handler подключены к A scheduler composition на PostgreSQL 18 | `application/requests/deadline.py`, `application/agent/composition.py`, K10/K14 tests |
| K13: события продолжения | Частично: восемь событий связаны с fresh run; mutation handlers регистрируются раньше agent, `done` не закрывает дело; Z producers/process частично подключены, live inference не проверен | `application/agent/events.py`, `application/requests/events.py`, `application/agent/composition.py`, K/Z tests |
| K14: сквозная проверка | Частично: отдельно MAX inbox/triage и единая PostgreSQL production-цепь problem/request/PDF/executor/resolution до `closed` проверены; PDF связан с request | K14 tests, `tests/infrastructure/test_g3_runtime.py`; live MAX/LLM и MAX upload отсутствуют |
| K15: agent evals | Частично: оценщик, рубрика 24 кейсов и воспроизводимый Ollama route-harness проверены unit-тестами; полные реальные model metrics ещё не измерены | `scripts/evaluate_agent.py`, `scripts/run_triage_evals.py`, `evals/k15-status.md`, K15 tests |
| K16: demo handoff | Частично: четыре вариативных пути и provenance подготовлены; live MAX/G3 evidence ещё отсутствуют | `docs/release/katerina-demo-handoff.md`, `docs/release/max-mobile-web-matrix.md` |
| Хранение опросов и production-интеграция агента | Частично: ordinary problem open/outcome и initiative open/decision, Z ORM/callback/cards/jobs подключены; автоматический request без actor/rule запрещён | production case/initiative/poll modules, `entrypoints/processes.py`, tests |
| Z-MVP-1: вход до обращения | Частично: вопрос/уточнение, приватные `/evidence` и `/assess`, авторская `/revise`, проверенное `/prepare`, явные `/approve` и `/send` подключены к production inbox; дедупликация/replay и запрет чужому actor проверены на PG16. Problem/initiative/emergency typed routes сохраняют прежние локальные проверки | `application/agent/resident_actions.py`, `resident_production.py`, `entrypoints/processes.py`, `tests/agent/test_z_mvp1_message_actions.py`, `tests/infrastructure/test_z_mvp1_resident_actions.py`; live MAX/mobile/web и вариативные формулировки ещё не проверены |
| Тесты и проверенный стенд | Частично: 303 теста на чистой PostgreSQL 17/pgvector после полной миграции и двойного seed; Ruff, format, mypy и Alembic check прошли. Девять локальных production G3 цепей, callback G3 и A-MVP-1 live spine проверены | `tests/`, `migrations/`, `docs/release/a-mvp-1-evidence.md`; mobile/web и полный live G3 не проверены |

Наличие схем, таблиц, примеров и списка технологий не означает, что функция работает. Доступ к токену MAX, серверу и inference не считается полученным без фактической проверки.

### Финальные задачи MVP: два параллельных трека (30.09.2026)

Для текущего финиша команда распределяет оставшуюся работу между **Алиной** и
**Замирой**. Исторические A/K/Z задачи выше и в `context/tasks-*.md` остаются
источником требований, но не списком работ, которые нужно заново реализовать.
Два агента начинают от одного актуального `main` в **разных worktree/ветках**.
После каждого ID — отдельный коммит, проверка и обновление фактического статуса.
Одновременно не редактировать чужой участок; сначала согласовать изменение
общего contract, затем его потребителей. Замира на этот финиш берёт открытые
MVP-стыки K (агент/дела/обращения), ранее закреплённые за Катериной; это
перераспределение, а не повод переписывать готовые K модули. Алине принадлежат
`entrypoints/processes.py`, MAX transport, deploy, CI и базовые contracts;
Замира меняет K/Z application/domain и их tests. Новые события и DTO фиксируются
маленьким contract commit до совместного live прогона.

| Имя для поручения агенту | Владелец и конкретный остаток | Условие завершения |
|---|---|---|
| **A-MVP-1 — стенд и inference** | Алина: воспроизводимый PG17/pgvector + миграции и Compose, выбранный Ollama/model revision в process root, готовность всех workers, доступный режим MAX (polling либо публичный HTTPS webhook), безопасная конфигурация/секреты. | Из чистого checkout поднимается один стенд; `/me` и модель отвечают; normal MAX message проходит durable inbox → agent → outbox. Записаны commit, model revision, режим ingress и фактические ограничения. Локальный Ollama probe из другой ветки не засчитывается за общий live путь. |
| **A-MVP-2 — MAX transport и наблюдаемость** | Алина: реальные group/DM/callback, вложение фото и PDF, edit карточки, signed chat IDs, недоступная личка, bounded retry/lease и диагностические read-only команды. Проверить официальные методы MAX перед правкой. | Подтверждённый actor/дом передаются Z/K, доставленный файл открывается web/mobile; чужой и старый callback не меняют голос; timeout/потеря прав не объявляются `sent`. Evidence ref попадает в доверенное событие без текста/токена в публичном логе. |
| **A-MVP-3 — эксплуатация и выпуск** | Алина: общий PG17 CI после слияния, рестарт/backup/restore, G0–G3 runtime runbook, MAX mobile/web матрица вместе с Замирой, secret/license audit, image digests/архив и tag только после пройденного G3. | Чистый стенд восстанавливается из backup; все обязательные проверки имеют дату/commit и реальные результаты; release package содержит demo/live inventory. Выбор лицензии собственного кода запрашивается у команды как отдельное решение перед NOTICE/tag. |
| **Z-MVP-1 — вход до обращения** | Замира: закрыть открытые K/Z application-стыки от живого текста: вопрос/уточнение, problem/initiative/emergency, дедупликация, привязка фото к делу и assessment, авторская редакция инициативы, reviewed rule/ответственный, явное согласование/submit жителем. Начать с локальных typed/PG тестов поверх существующих A ports. | Ни один route не создаёт фиктивный успех; инициатива после поддержки ведёт к request только с подтверждённым actor и правилом; фото сохраняется как evidence без выдуманного vision; emergency не ждёт poll. В MAX проходят вариативные формулировки, не один заученный текст. |
| **Z-MVP-2 — голос, карточка и PDF** | Замира: довести frozen audience, личные приглашения, допустимый callback/feedback, edit и финализацию карточки, ревизию инициативы, четыре приватных PDF через настоящий FileStore/outbox/MAX. Локальные tests покрывают replay/concurrency и приватность, live запуск — после A-MVP-1/2. | Один житель — один голос; недоставка не меняет знаменатель; старая кнопка не действует; публично только агрегаты; четыре Z PDF читаются в MAX mobile и web, адресат и snapshot/hash совпадают. |
| **Z-MVP-3 — результат, evals и демо** | Замира: demo-only register/status/done, исходная аудитория, `closed`/`reopened`/`resolution_unconfirmed`, дедлайн/черновик жалобы, восстановление после повторов; K01/K15 evals выбранной модели и совместный с Алиной live G3. | Пройдены problem, initiative и emergency, положительный и отрицательный исходы и молчание по demo policy; `done` само не закрывает дело. Зафиксированы model/prompt/policy revisions, критические ошибки evals и точные шаги показа без ручной правки live БД. |

Статус A-MVP-1 на 30.09.2026: **проверено** в ветке `a-mvp-1` на implementation commit
`b9de58f`. Clean polling stand подтвердил PG17/pgvector, миграции/runtime seed, MAX `/me`,
отсутствие webhook, выбранный Ollama `qwen3:4b`, все workers и live normal group message по
цепочке durable `inbox → agent/tools → sent outbox`. Полный G3 не объявлен: следующий
`problem.detected` ждёт Z-MVP-1 handler. Evidence и ограничения —
`docs/release/a-mvp-1-evidence.md`.

Статус A-MVP-2: начата ветка `a-mvp-2`. Добавлена read-only диагностика inbox/outbox/jobs:
агрегаты status/ready/stale lease и явные alerts без payload, текста, токенов или MAX ID.
Добавленная redacted проверка отправленного MAX-сообщения по `mid` прошла на реальном текстовом
сообщении: наружу вышли только признак текста и типы вложений. Она не заменяет ручное открытие
файла в web/mobile.
Транспортные live-пункты (фото, допустимый callback/edit, потеря прав и mobile/web) ещё не
закрыты; наличие CLI не считается их подтверждением.
Recovery старого `problem.detected` выявил сохранённое моделью дело с floor без entrance:
production scope guard закономерно отказал. Контракты `case.search`/`case.create` теперь запрещают
такую комбинацию до handler, а MAX handler ставит понятное уточнение места в outbox при
`VALIDATION_ERROR`. Исправление проверено локально; старое некорректное дело не переписывалось.

**Порядок:** A-MVP-1 и Z-MVP-1 можно писать независимо; A-MVP-2 и
локальную часть Z-MVP-2 — параллельно. Совместная MAX проверка Z-MVP-2 ждёт
стенд/transport A; Z-MVP-3 использует их готовые версии. A-MVP-3 фиксирует
релиз после совместного G3. При конфликте не заменяй незаконченный контракт
прямым импортом соседнего репозитория: дай typed fake и конкретный handoff.
Перечень исторических задач и ворот — в
[плане](context/implementation-plan.md), текущие пробелы — в
[состоянии](context/current-state.md).

**После каждого контрольного рубежа агент пишет пользователю, что именно
проверить руками в приложении MAX**, в mobile и web, с ожидаемым результатом,
синтетическими ролями и ссылкой на строку
[матрицы](docs/release/max-mobile-web-matrix.md). Не ставь отметку
`проверено` до фактического ответа/свидетельства человека.

1. **После A-MVP-1 + локального Z-MVP-1:** `/start` в личке, выбор demo-дома,
   вариативное сообщение о проблеме/аварии/инициативе в группе, ответ агента
   и отсутствие ответа от имени чужого дома.
2. **После A-MVP-2 + Z-MVP-2:** 12 синтетических жителей; три допустимых
   подтверждения дают `3/12`, повтор не увеличивает счётчик, смена голоса
   обновляет ту же карточку; чужая/устаревшая кнопка отклоняется, фото приходит
   приватно; четыре PDF открываются в обоих клиентах и не появляются в группе.
3. **После Z-MVP-3:** operator `register`/`done`, личный опрос исходной
   аудитории, отдельные `closed`/`reopened`/`resolution_unconfirmed`; остановить
   личку одному жителю, перезапустить worker, проверить повтор и недоставку.
   Финализация result poll ждёт установленный срок; не править live БД ради демо.
4. **Перед A-MVP-3/tag:** пройти всю
   [матрицу MAX](docs/release/max-mobile-web-matrix.md) на общем commit и
   записать реальные версии клиентов, время и обезличенное evidence.

Можно поручать по имени: «Реши A-MVP-1 из AGENTS.md» или «Реши Z-MVP-1 из
AGENTS.md». Запрос «закрой трек Алины/Замиры» означает пройти его ID
последовательно с отдельными проверками/коммитами, а не объявить MVP готовым
после первого сценария.

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

Команды работают локально после A00; объединённый commit прошёл на чистой PG16.13, предыдущий набор — GitHub Actions #50 на PG17/pgvector. Для документационных изменений достаточно проверки ссылок, согласованности и `git diff --check`; не создавай тесты приложения ради Markdown-правки.

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
