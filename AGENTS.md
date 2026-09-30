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

**Состояние проверено 30.09.2026: локально пройдены 277 тестов на чистой PostgreSQL 16.13, включая problem → MAX callback/карточка → request/PDF → demo executor → closed/reopened. Ранее live MAX проверил `/me`, polling, demo-онбординг, доставку карточки группы и отказ callback вне аудитории; допустимый live голос/edit/PDF и цельный MAX/LLM G3 не проверены.**

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
| AudienceService Z03 | Частично: PostgreSQL snapshot/revision/idempotency и конкурентный successor проверены на локальной PostgreSQL 16; стык K ещё не подключён | `application/audiences/service.py`, `infrastructure/postgres/audiences.py`, `migrations/versions/63a9d1e4bc02_z03_audiences.py`, `tests/infrastructure/test_z03_audiences_postgres.py` |
| PollService Z04 | Частично: PostgreSQL ответы, история, deadline job и threshold/expiry inbox проверены на PostgreSQL 16; production callback/scheduler подключены, K route и live MAX не проверены | `infrastructure/postgres/polls.py`, `z_poll_models.py`, `migrations/versions/9d20b8a6c743_z04_polls.py`, `tests/infrastructure/test_z04_polls_postgres.py` |
| Callback handler Z05 | Частично: 30.09.2026 голос, личный outbox и edit карточки атомарно проверены на PostgreSQL/MockTransport; actor/дом, frozen audience, повторы, смена выбора, срок, закрытие, stale и конкурентные callback покрыты. Ранее live callback вне аудитории отклонён; допустимый live голос и отображение ЛС в web/mobile ещё не проверены | `application/polls/production.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py` |
| InitiativeService Z06 | Частично: durable opening создаёт frozen audience/revision/poll/reminders/card; decision атомарно переводит case в `request_ready` или `not_supported` | initiative production/followup repositories и tests; подготовка request ждёт подтверждённого actor и проверенного правила, live MAX отсутствует |
| Публичные карточки Z07 | Частично: callback автоматически ставит edit после принятия/смены голоса; возврат счётчика к исходному значению supersede-ит ожидающий edit. PostgreSQL/MockTransport проверены 30.09.2026; ранее live карточка с кнопками доставлена, live edit ещё не проверен | `application/cards/production.py`, `application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`, `test_z07_cards_outbox.py` |
| Напоминания и итог инициативы Z08 | Частично: два durable job при открытии, rights/frequency/outbox и итог поддержана/не поддержана проверены на PostgreSQL 16; DOMAIN poll expiry и reminder handler подключены к process root, K переход в исполнение отсутствует | `infrastructure/postgres/initiatives.py`, `initiative_followup.py`, `application/resolution/production.py`, `tests/infrastructure/test_z08_followup_postgres.py` |
| FileStore и снимок документа Z09 | Частично: registration event создаёт idempotent appeal snapshot из сохранённых case/request/poll/audience фактов, включая emergency frozen audience без начального poll | document production/runtime tests; live MAX не проверен |
| PDF-рендер Z10 | Частично: 4 шаблона прошли единый локальный PostgreSQL/process pool → FileStore → приватный outbox → MAX upload/DM MockTransport 30.09.2026; lease/recovery проверены отдельно. Live MAX download ещё не проверен | `application/documents/worker.py`, `tests/infrastructure/test_z10_max_pdf_pipeline.py`, `test_z09_documents_postgres.py`, `docs/release/zamira-live-pdf-smoke.md` |
| DemoExecutor Z11 | Частично: PostgreSQL idempotency/конкуренция, approved draft, права и события/outbox проверены локально; доверенный demo-only operator CLI для register/done/replay добавлен 30.09.2026. Live G3 не проверен | `infrastructure/postgres/demo_executor.py`, `entrypoints/zamira_operator.py`, `tests/infrastructure/test_z11_demo_executor_postgres.py`, `tests/entrypoints/test_zamira_operator.py` |
| Проверка результата Z12 | Частично: доверенный `done`, исходная аудитория problem/initiative/emergency, poll/jobs/outbox и переход `checking_resolution` подключены и проверены на PostgreSQL | resolution/emergency runtime modules и tests; live MAX ещё не проверен |
| Итог результата Z13 | Частично: три исхода, case event, отмена pending jobs и `resolution.rejected` проверены на локальной PostgreSQL 16; scheduler/DOMAIN handler подключён | Те же модули и тесты; полный G3/live MAX ещё не проверены |
| Сквозная проверка Z14 | Частично: единый локальный PostgreSQL/MockTransport путь problem → MAX callback → голос/card edit → request/PDF/FileStore/binding → demo executor → resolution → closed/reopened проверен 30.09.2026; полный live MAX/LLM G3 не проверен | `tests/infrastructure/test_g3_runtime.py`, `test_z10_max_pdf_pipeline.py` |
| PDF QA Z15 | Частично: ранее визуально просмотрены 4 образца/7 страниц; 30.09.2026 локально проверены hash, текст, демо-маркировка и приватная MAX MockTransport-доставка всех четырёх PDF. MAX mobile/web файлы не просмотрены | `docs/release/zamira-pdf-qa.md`, `zamira-live-pdf-smoke.md`, `tests/infrastructure/test_z10_max_pdf_pipeline.py` |
| Материалы Z16 | Частично: handoff и точный ручной сценарий двух исходов с demo-only operator CLI подготовлены; локально проверены. Live MAX/mobile-web и двухчасовая финализация на стенде не проверены | `docs/release/zamira-handoff.md`, `zamira-manual-demo.md`, `entrypoints/zamira_operator.py`, `tests/entrypoints/test_zamira_operator.py` |
| Python-проект, зависимости и CI A00 | Проверено локально; предыдущий набор — GitHub Actions #35 | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; локально на целевом PG17/pgvector migration/check, 274 теста, Ruff и mypy по `src` прошли; CI нового набора ожидается |
| PostgreSQL core A02 | Проверено локально на PostgreSQL 17.8 + pgvector 0.8.1 | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`; общая migration/check до Z head и 274 теста на чистой БД |
| HouseContextPort A05 | Частично: чтение реестра и стык с Z проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: operator CLI, приглашение, signed int64 group chat ID, привязка MAX ID/чата, stopped и выбор дома проверены на PostgreSQL; реальные `/start <код>` и привязка группы подтверждены | `entrypoints/demo_operator.py`, `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, tests; mobile и несколько домов ещё не проверены |
| MAX Bot API A03 | Частично: HTTPX MockTransport, live `/me`, личная и групповая отправка, а также `POST /answers` с непустым notification проверены 29–30.09.2026 | `infrastructure/max/client.py`, `tests/infrastructure/test_max_client.py`; upload ещё требует live smoke |
| Webhook/inbox A04 | Частично: text/callback/attachment refs/deletion/lifecycle/membership/admin permissions и unknown Update проверены через ASGITransport + PostgreSQL; live polling принял `bot_started` и `message_created` | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`; публичный HTTPS webhook и прочие live-типы ещё не проверены |
| Inbox worker A07 | Частично: lease/recovery/retry и production loop с K/Z handlers проверены локально | `entrypoints/processes.py`, `application/jobs/inbox_worker.py`, K/Z tests; live MAX не проверен |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, signed group ID, DM, карточка/edit, недоступный адресат и отдельный process loop проверены на PostgreSQL 17 + MockTransport; durable личная, групповая и карточка с кнопками реально отправлены в MAX | `entrypoints/processes.py`, `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`; live edit/PDF delivery ещё требуют smoke |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency, stale no-op и K/Z handlers в production loop проверены локально | `entrypoints/processes.py`, `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`; live runtime не проверен |
| MAX poll callbacks A10 | Частично: actor/дом/токен, outcome-specific notification и Z PollRepository проверены на PostgreSQL/MockTransport; live группа передала callback, сервер корректно не записал голос жителя вне frozen audience, прямой notification принят MAX | `infrastructure/postgres/poll_actions.py`, `application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`; live допустимый голос и edit ещё не проверены |
| MAX files A11 | Частично: PDF upload, token reuse/retry, безопасное фото, локальные rate limits и coalescing edit проверены unit/MockTransport; PostgreSQL-сценарии требуют test DB | `infrastructure/max/media.py`, `infrastructure/max/evidence.py`, `infrastructure/max/rate_limit.py`, tests; live MAX mobile/web и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: полный Compose с Z document worker локально запускает и перезапускает migrate/API/inbox/scheduler/outbox/documents/maintenance/Caddy; HTTPS readiness различает БД и LLM; наружу опубликован только Caddy | `Dockerfile`, `deploy/compose.yml`, `entrypoints/api.py`, `entrypoints/processes.py`; публичный DNS/TLS, выбранная модель и live MAX/inference не проверены |
| Надёжность A13 | Частично: bounded retry, dead-letter, `delivery_unknown`, rate limits, coalescing и lease heartbeat проверены локально | `application/notifications/worker.py`, `application/jobs/scheduler.py`, infrastructure queue tests; live потеря прав/rate limits не проверены |
| Composition/polling A14 | Частично: локальная production-цепь problem → request → PDF/FileStore/binding → demo registration/done → resolution poll → closed проверена через dispatcher/repositories | `tests/infrastructure/test_g3_runtime.py`; без LLM и MAX upload/delivery это не live G3 |
| Backup/restore A15 | Проверено локально на PostgreSQL 17.8/pgvector и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, retention tests; восстановлены Z head `0a7b6c5d4e3f`, vector, 40 public tables и 5 file hashes; PostgreSQL/FileStore named volumes пережили Compose restart |
| MAX matrix A16 | Не проверено; подготовлен протокол без фиктивных отметок | `docs/release/max-mobile-web-matrix.md`; нужен live бот, mobile/web и общий runtime |
| Release A17 | Частично: runbook, env placeholders, secret/history audit, transitive license inventory и evidence/archive tool подготовлены | `scripts/release_audit.py`, `docs/release/platform-operations.md`; история чиста, но лицензия собственного проекта не выбрана; tag/digests допустимы только после G3 |
| K00: стыки агента, дел и знаний | Проверено локально: единый реестр девяти K tools связан с runtime и production K services | `src/dom_domych/agent/contracts.py`, `tool_handlers.py`, `tools.py`, `application/agent/composition.py`, K00/K03/K11 tests |
| K01: eval dataset | Проверен формат и покрытие; модель не запускалась | `evals/k01_cases.jsonl`, `evals/README.md`, `tests/agent/test_k01_dataset.py` |
| K02: inference | Частично: OpenAI-compatible и нативный Ollama adapters, fake/timeout/retry проверены; локальный `qwen3:4b` выполнил структурированные tool calls в production-подобном PostgreSQL-прогоне, но evals и метрики не пройдены | `src/dom_domych/agent/llm.py`, `infrastructure/llm/llama_server.py`, `infrastructure/llm/ollama.py`, K02 tests, `docs/engineering/11-track-k-inference-probe.md` |
| K03: agent runtime | Частично: allowlist/schema/capability/budget и девять K tools собраны с production K services; backend подставляет доверенные source/idempotency IDs, локальный inference прошёл `case.search` → `case.create` → reply outbox | `src/dom_domych/agent/runtime.py`, `agent/tools.py`, `application/agent/composition.py`, K03/K14 tests; полный MAX/G3 и evals ещё не проверены |
| K04: continuation | Частично: PostgreSQL runs/pending/tool audit, fresh context и K dispatcher/scheduler composition проверены локально; production process подключён | `src/dom_domych/agent/continuation.py`, `application/agent/composition.py`, K04/K14 tests; live inference не проверен |
| K05: knowledge | Частично: разрешённый HTTPS ingestion, review, русская FTS и scoped rules проверены на PostgreSQL 18; PG17/pgvector/live embeddings не проверены | `application/knowledge/service.py`, `infrastructure/postgres/knowledge.py`, `infrastructure/llm/embeddings.py`, `tests/infrastructure/test_k05_knowledge.py` |
| K06: triage | Частично: пять маршрутов, несколько тем и срочный guard подключены к MAX inbox; actor/дом берутся из подтверждённого проживания, один завершающий JSON безопасно извлекается из ответа локальной модели, ответ ставится в outbox; live eval отсутствует | `agent/triage.py`, `application/agent/messages.py`, `infrastructure/postgres/message_agent.py`, K06/K14 tests |
| K07: case retrieval | Частично: house/location/object/30-day closed filters и FTS проверены на PostgreSQL 18; PG17/pgvector branch не проверена | `application/cases/candidates.py`, `infrastructure/postgres/case_candidates.py`, `tests/infrastructure/test_k07_candidates.py` |
| K08: CaseService | Частично: create/attach/recurrence, events, idempotency, конкурентный dedupe и Z06 case/author adapter проверены на PostgreSQL 18; Z transactional repository теперь есть, K route ещё не подключён | `application/cases/service.py`, `infrastructure/postgres/case_writer.py`, `initiative_cases.py`, K08/Z06 tests |
| K09: обычная проблема | Частично: production route сохраняет audience/poll/deadline/case/card-outbox; live сообщение о проблеме прошло LLM → case → frozen audience/poll/job → групповую карточку. Trusted outcome переводит дело в request_ready либо needs_evidence; evidence assessment сохраняет проверенные refs отдельно | `application/cases/production.py`, `application/cases/evidence.py`, `infrastructure/postgres/case_evidence.py`, `tests/infrastructure/test_k09_evidence.py`; live порог/request/evidence цикл ещё не пройден |
| K10: RequestService | Частично: verified rule, draft/approval/submit/registration и production appeal snapshot/ready binding проверены на PostgreSQL; live delivery отсутствует | request/document production modules, K10/Z09/Z11/problem runtime tests |
| K11: emergency | Частично: typed agent tool не ждёт poll; durable `emergency.detected` фиксирует исходную аудиторию для PDF/result, evidence остаётся личным | emergency application/runtime modules и tests; live MAX не проверен |
| K12: deadline | Частично: job ставится при доверенной регистрации; due создаёт review-only followup с повторной проверкой версии/статуса, K revision/handler подключены к A scheduler composition на PostgreSQL 18 | `application/requests/deadline.py`, `application/agent/composition.py`, K10/K14 tests |
| K13: события продолжения | Частично: восемь событий связаны с fresh run; mutation handlers регистрируются раньше agent, `done` не закрывает дело; Z producers/process частично подключены, live inference не проверен | `application/agent/events.py`, `application/requests/events.py`, `application/agent/composition.py`, K/Z tests |
| K14: сквозная проверка | Частично: отдельно MAX inbox/triage и единая PostgreSQL production-цепь problem/request/PDF/executor/resolution до `closed` проверены; PDF связан с request | K14 tests, `tests/infrastructure/test_g3_runtime.py`; live MAX/LLM и MAX upload отсутствуют |
| K15: agent evals | Частично: оценщик и рубрика 24 кейсов проверены unit-тестами; реальные model metrics не измерены из-за нехватки памяти доступного Mac | `scripts/evaluate_agent.py`, `evals/k15-status.md`, `tests/agent/test_k15_evaluator.py` |
| K16: demo handoff | Частично: четыре вариативных пути и provenance подготовлены; live MAX/G3 evidence ещё отсутствуют | `docs/release/katerina-demo-handoff.md`, `docs/release/max-mobile-web-matrix.md` |
| Хранение опросов и production-интеграция агента | Частично: ordinary problem open/outcome и initiative open/decision, Z ORM/callback/cards/jobs подключены; автоматический request без actor/rule запрещён | production case/initiative/poll modules, `entrypoints/processes.py`, tests |
| Тесты и проверенный стенд | Частично: 30.09.2026 на чистой PostgreSQL 16.13 прошли 277 тестов, Ruff и mypy по `src`; предыдущие 274 теста/Alembic check прошли на PG17.8 + pgvector 0.8.1. Live MAX group → problem poll/card и отказ callback вне аудитории ранее проверены | `tests/`, `migrations/`; цельный MAX/LLM G3, допустимый live голос/edit и files ещё не проверены |

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
