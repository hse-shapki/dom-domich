# Проверенное состояние проекта

Проверено 26.09.2026 по ветке `kae`. Этот файл меняется после реализации задач; старое значение статуса не является вечной истиной.

## Факты на дату проверки

После слияния `main` в `kae` K00 contracts используют общий A01
`TrustedContext`/`ToolResult`; девять schemas связаны с production K services
через единый tool registry. Z production ports остаются внешней зависимостью.
K01: подготовлен русский набор из 24 синтетических кейсов и нулевой baseline
в `evals/`; прогон реальной модели пока не выполнен.
K02: `LlmPort`/fake/retry и HTTPX adapter проверены MockTransport. Модели
проверены по SHA-256 и удалены из cache; `llama.cpp` доступен локально.
На 8 GiB Mac текстовая модель не дала
успешного ответа: полный Metal offload упёрся в память, CPU превысил 120 с,
частичный offload вызвал swap. Live inference и p50/p95 не подтверждены;
подробности: `docs/engineering/11-track-k-inference-probe.md`.
K03: runtime проверяет allowlist, JSON schema, режим, capability и бюджет;
единый реестр связывает девять опубликованных K schemas с KToolHandlers,
включая срочный `emergency.handle` без ожидания опроса;
production K case/knowledge/request services собираются одним composition helper.
Runtime связывает ответ с tool call ID, сохраняет краткий audit и не выдаёт ошибку
handler за успех. Production K handlers и вход из inbox подключены; live inference
и Z production ports отсутствуют.
K04: `ContextBuilder` перечитывает текущую версию дела и actor-scoped pending
question. PostgreSQL хранит runs, pending questions и краткий tool audit;
миграция, восстановление и composition с inbox проверены на PostgreSQL 18.
K05: разрешённый HTTPS источник поступает как непроверенная версия, затем
явно review; поиск использует русскую FTS по проверенным версиям и изолирует
дома. Rule требует проверенного источника, scope и явной точки отсчёта срока.
PostgreSQL 18 migration/search и HTTPX embedding adapter проверены локально;
ветка pgvector в целевом PG17 и live embedding не проверены.
K06: типизированная классификация пяти типов и разделение нескольких проблем
в сообщении проверены fake tests. Срочные выражения имеют консервативный
fallback; вопрос без проверенного источника ведёт к уточнению. Сервис отдаёт
маршрут в agent coordinator из общего inbox. PostgreSQL resolver выдаёт actor,
дом и настроенные capabilities только активному подтверждённому жителю; ответ
сохраняется в outbox. Живые agent evals не измерены.
K07: созданы `cases` и поиск кандидатов с домом, локацией, объектом, FTS,
недавно закрытыми делами и консервативным vector fallback. Миграция и
изоляция домов/подъездов проверены на PostgreSQL 18 без pgvector;
vector branch и реальные embeddings ещё не проверены.
K08: CaseService проверяет доверенный event/actor/capability, PostgreSQL
writer под advisory lock повторяет поиск кандидатов, хранит operation hash,
case messages, versioned events и recurrence. Тест на PostgreSQL 18 провёл
12 конкурентных сообщений к одному делу, повтор операции, stale version,
два дела в одном сообщении и чужой дом. Evidence-таблица есть, но её
application use case и сквозная связка с A/Z ещё не подключены.
Для Z06 добавлен scoped reader автора инициативы из неизменяемой origin-связи;
он не принимает author/house из аргументов модели. Z repository/UoW ещё отсутствует.
K09: ProblemWorkflow проверяет scope дела, создаёт frozen audience/poll на
fake atomic store, не открывает опрос при N=0 и передаёт адресный evidence
запрос только ответившим «да» по доверенному итогу Z. EvidenceService пишет
private ref и versioned event на PostgreSQL 18. Production объединение Z poll,
case/outbox/jobs в одной UoW отсутствует, поэтому сквозной маршрут не готов.
K10: RequestService сверяет актуальную версию дела и проверенное правило,
хранит draft hash/version и явное согласование. Изменение черновика сбрасывает
approval, submit в demo идемпотентен через operation key, статус registered
появляется только от доверенного DemoOperation. Готовый документ теперь связывается
с request по `DocumentPort` с проверкой дома/case/hash/file key. Миграции и цикл
проверены на PostgreSQL 18 с fake Z ports; production Z Document/Executor repositories
ещё отсутствуют.
K11: EmergencyService готовит draft сразу после проверки места и ответственного,
не зависит от poll; при пробеле в месте/источнике возвращает точное уточнение,
не выдумывает срок. Evidence intent идёт только в личный outbox, идемпотентен
на PostgreSQL 18. Use case опубликован как typed agent tool и собран с production
K services; fake route и PostgreSQL tests проходят. Live MAX и production Z
executor не подключены.
K12: при доверенной регистрации проверенное и применимое правило с origin
`request.registered` ставит job атомарно с обновлением дела. Due handler повторно
проверяет house/version/status под lock и сохраняет черновик followup со ссылками
на регистрацию и источник; отправку не утверждает. K handler/revision reader
подключены к A scheduler composition и проверены на PostgreSQL 18. Production
process, live MAX и нормативная ревизия источников не проверены.
K13: bridge принимает poll/evidence/request/resolution/document события только от
доверенных источников, разрешает case в доме и запускает новый followup run с
актуальной версией дела. Перед continuation `request.status_changed` перечитывается
через `ExecutorPort`, а `document.ready` — через `DocumentPort`; внешний статус и
immutable document refs сохраняются отдельно от workflow в одной транзакции с
versioned case event. `done` не закрывает дело. Повтор завершённого события не
вызывает inference, неуспешный run может повториться. `request.registered` и
`evidence.added` атомарно пишутся в domain inbox. Новый consumer и migration/check
проверены на PostgreSQL 18; producers Z, общий production worker и live inference
ещё не подключены.
K14: сквозная локальная проверка проходит от due job A через production K
composition и followup draft до сохранённого нового agent run на PostgreSQL 18
с fake LLM/Z ports. Повтор, устаревшая версия и чужой дом проверены; полный Z poll/PDF/MAX путь пока
невозможен без production ports/composition.
Отдельно проверен путь нормализованного MAX message через durable inbox,
подтверждённое проживание, typed triage и production `case.create` до agent run
и reply outbox; реальный MAX при этом не использовался.
K15: оценщик traces считает маршруты, критические ошибки, источник, задержки
и tool calls по K01 dataset; unit-тесты проходят. Реальные метрики модели
не измерены: Qwen3-8B на 8 GiB Mac не дал ответа и вызвал swap. Версии и
ограничения записаны в `evals/k15-status.md` и K02 probe.
K16: четыре вариативных демо-пути, ссылки на проверяемые тесты и provenance
собраны в `docs/release/katerina-demo-handoff.md`; live MAX/G3 evidence не
заполнены. Устаревшее описание A00 в Z handoff исправлено.

| Область | Состояние | Проверяемое основание |
|---|---|---|
| Продуктовая концепция и журнал решений | Есть документация | `IDEA.md`, `docs/backlog.md`, `docs/open-questions.md` |
| Техническая архитектура, ограничения, треки и приёмка | Есть проектная документация | `docs/engineering/README.md` и восемь документов в той же папке |
| Персональные пулы технических задач | Спланированы; A00–A13/A15–A17 и часть Z реализованы локально или частично | `context/implementation-plan.md`, `tasks-alina.md`, `tasks-katerina.md`, `tasks-zamira.md` |
| Корневые правила для агентов | Есть | `AGENTS.md` |
| Постоянный контекст | Есть | `context/README.md`, `decisions.md`, `product.md`, `engineering.md`, `current-state.md` |
| Чистые доменные правила опросов Z01 | Проверены на unit-уровне | `src/dom_domych/domain/polls/policy.py`, `tests/domain/test_poll_policy.py`: 23 теста |
| Общие контракты A01 / предложения K00/Z00 | Частично: DTO/ports и K tool registry совместимы; production K services собраны, Z repositories не связаны | `src/dom_domych/contracts/`, `src/dom_domych/domain/ports/core.py`, `src/dom_domych/application/agent/composition.py`, K00/K03/K14 tests |
| Синтетический дом Z02 | Проверен как fixture и seed A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`, `scripts/seed_demo_house.py`: 4 fixture-теста |
| AudienceService Z03 | Частично: выбор и история snapshot проверены на fake | `src/dom_domych/domain/audiences/models.py`, `src/dom_domych/application/audiences/service.py`, `tests/domain/test_audience_service.py`; нет PostgreSQL repository/migration |
| PollService Z04 | Частично: поведение и конкуренция проверены на fake | `src/dom_domych/domain/polls/models.py`, `src/dom_domych/application/polls/service.py`, `tests/domain/test_poll_service.py`; нет PostgreSQL repository/migration и MAX callback |
| Callback handler Z05 | Частично: token/actor/revision/expiry проверены на fake | `src/dom_domych/application/polls/callback.py`, `tests/domain/test_poll_callback.py`; A10 MAX transport/action storage существуют, production PollRepository ещё не подключён |
| InitiativeService Z06 | Частично: K case/author reader проверен на PostgreSQL 18, редакции и замена poll — на fake | `infrastructure/postgres/initiative_cases.py`, `application/initiatives/service.py`, tests; нет PostgreSQL UoW инициатив/опросов и MAX token revocation |
| Публичные карточки Z07 | Частично: тексты/шкалы проверены unit-тестами | `src/dom_domych/application/cards/builders.py`, `tests/domain/test_public_cards.py`; A DeliveryPort/edit существует, карточки и coalescing ещё не подключены |
| Напоминания и итог инициативы Z08 | Частично: частотный лимит и supported/not_supported проверены на fake | `src/dom_domych/application/initiatives/followup.py`, `tests/fakes/initiative_followup.py`, `tests/domain/test_initiative_followup.py`; A DeliveryPort/jobs существуют, Z/K production wiring ещё нет |
| FileStore и immutable snapshot Z09 | Частично: проверены локально | `src/dom_domych/infrastructure/files/local.py`, `src/dom_domych/domain/documents/snapshot.py`, тесты в `tests/infrastructure/` и `tests/domain/test_document_snapshot.py`; нет PDF worker и PostgreSQL metadata |
| PDF-рендер Z10 | Частично: 4 шаблона проверены локально | `src/dom_domych/infrastructure/documents/renderer.py`, `tests/infrastructure/test_pdf_renderer.py`, 4 синтетических образца в `output/pdf/`; A08/A11 transport есть, durable PDF job и сквозная доставка не подключены |
| DemoExecutor Z11 | Частично: команда и переходы проверены на fake | `src/dom_domych/domain/executor/models.py`, `src/dom_domych/application/executor/service.py`, `tests/fakes/executor.py`, `tests/domain/test_demo_executor.py`; нет PostgreSQL repository/outbox и связи с K RequestService |
| Старт проверки результата Z12 | Частично: done → исходная аудитория/poll проверены на fake | `src/dom_domych/domain/resolution/models.py`, `src/dom_domych/application/resolution/service.py`, `tests/fakes/resolution.py`, `tests/domain/test_resolution_service.py`; нет K CasePort, PostgreSQL UoW и MAX-доставки |
| Итоги проверки результата Z13 | Частично: closed/reopened/unconfirmed проверены на fake | Те же файлы resolution; отдельный K production transition и отмена jobs ещё нужны |
| PDF QA Z15 | Частично: локально просмотрены 4 образца | `docs/release/zamira-pdf-qa.md`; mobile/web MAX и outbox ещё не проверены |
| Материалы Z16 | Частично: локальный handoff и воспроизведение PDF готовы | `docs/release/zamira-handoff.md`, `scripts/generate_zamira_demo_pdfs.py`; сквозной runbook ждёт A/K интеграции |
| Python-проект и зависимости A00 | Проверено локально | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; `uv sync --locked`, Ruff, mypy, 222 tests прошли; удалённый CI ещё не запускался |
| PostgreSQL core A02 | Частично: проверено на локальном PostgreSQL 18 | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`: migration/check и повторный seed; PG17/pgvector Compose не запущен |
| HouseContextPort A05 | Частично: выборка и интеграция с Z AudienceService проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: приглашение, привязка MAX ID, DM `/start`, stopped и выбор дома проверены локально | `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, `tests/infrastructure/test_demo_enrollment.py`; выдача кодов реальным operator и live MAX ещё не подключены |
| MAX Bot API A03 | Частично: документированные методы проверены через MockTransport | `infrastructure/max/client.py`, `tests/infrastructure/test_max_client.py`; upload bytes добавлен в A11, реальный токен/бот не проверены |
| Webhook/inbox A04 | Частично: text/callback/attachment refs/deletion/lifecycle/membership/admin permissions и unknown Update, dedupe/durable insert проверены на PostgreSQL 18 | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`, `tests/infrastructure/test_max_webhook.py`; HTTPS/MAX smoke отсутствует |
| Inbox worker A07 | Частично: lease/recovery/retry и K message handler проверены на PostgreSQL 18 | `application/agent/messages.py`, `infrastructure/postgres/message_agent.py`, inbox/K14 tests; production process и Z handlers ещё не подключены |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, DM, карточка/edit и недоступный адресат проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`, `tests/infrastructure/test_delivery_outbox.py`; PDF upload добавлен в A11, реальный MAX и production-процесс ещё не подключены |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency и stale no-op проверены на PostgreSQL 18 | `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`, `tests/infrastructure/test_scheduled_jobs.py`; revision adapter K/Z и production-процесс ещё не подключены |
| MAX poll callbacks A10 | Частично: actor/дом/токен и ACK проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/poll_actions.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_max_poll_callback.py`; Z PollRepository и live MAX ещё не подключены |
| MAX files A11 | Частично: PDF upload, token reuse/retry, безопасное фото, process-local rate limits и coalescing edit реализованы | `infrastructure/max/media.py`, `infrastructure/max/evidence.py`, `infrastructure/max/rate_limit.py`, tests; live MAX mobile/web и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: production Dockerfile, Compose/Caddy, API/outbox/retention lifecycle и health routes реализованы; Compose schema проверена | `Dockerfile`, `deploy/compose.yml`, `entrypoints/processes.py`, `docs/release/platform-operations.md`; Docker daemon, HTTPS и restart volumes не проверены, inbox/scheduler ждут K/Z wiring |
| Надёжность A13 | Частично: bounded retry/dead-letter/delivery_unknown, rate limits, coalescing и heartbeat outbox/jobs проверены | `infrastructure/max/rate_limit.py`, queue workers/repositories и PostgreSQL tests; live rate-limit и потеря прав MAX не проверены |
| Composition/polling A14 | Частично: dev polling сохраняет batch до marker; K message/continuation handlers и revision reader имеют production composition helper | `application/agent/composition.py`, `infrastructure/max/polling.py`, dispatcher/scheduler; process root и Z repositories отсутствуют |
| Backup/restore A15 | Проверено локально на PostgreSQL 18 и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, retention tests; восстановлены Alembic head, 2 дома/20 проживаний и PDF с тем же SHA-256, временные данные удалены |
| MAX mobile/web A16 | Не проверено; подготовлен честный протокол | `docs/release/max-mobile-web-matrix.md`; нужен live бот, два клиента и общий G3 runtime |
| Release A17 | Частично: secret audit текущих файлов/истории прошёл, 41 installed package инвентаризирован, archive/evidence tool готов | `scripts/release_audit.py`, `docs/release/platform-operations.md`; лицензия самого `dom-domych` не выбрана, tag/image digests нельзя фиксировать до G3 |
| Агент K00–K04 | Частично: contracts, dataset, production K tool composition и durable continuation проверены с fake LLM | `src/dom_domych/agent/`, `application/agent/composition.py`, `tests/agent/`, `evals/`; live inference и общий process открыты |
| Хранение опросов | Не реализовано | Z domain/application и A core есть; PostgreSQL repository/migration и wiring отсутствуют |
| Рабочий стенд и внешние проверки | Не подтверждены | Production Compose schema валидна, но Docker daemon недоступен; доступ MAX/модели, HTTPS, mobile/web и цельный runtime не проверялись |

Эти строки описывают только осмотр репозитория. Они не доказывают отсутствие внешнего аккаунта или бота у команды. И наоборот, схема в Markdown не доказывает готовность реализации.

## Следующий шаг по утверждённому плану

K handlers и repositories теперь собираются в отдельном composition helper для A dispatcher/scheduler.
Следующий блокирующий шаг — реализовать Z production repositories/producers и передать их в этот
helper из A14 process root; без них цельный inbox/scheduler нельзя запускать. Затем нужны
реальный MAX/LLM доступ, HTTPS smoke, PostgreSQL 17/pgvector restore test и G1–G3/mobile-web
прогоны. Все 222 tests, включая PostgreSQL integrations, прошли на локальной
PostgreSQL 18; целевые PostgreSQL 17/pgvector и Docker Compose не проверялись.

## Как обновлять после задачи

1. Сверить `git status`, файлы и результаты подходящих проверок.
2. Обновить только затронутые строки, указав пути к реализации и точную степень проверки: «частично», «реализовано, не проверено» или «проверено».
3. Синхронизировать раздел «Что уже сделано» в [AGENTS.md](../AGENTS.md) и при необходимости вводную страницу [инженерных документов](../docs/engineering/README.md).
4. Сохранить важный новый выбор в [решениях](decisions.md), а подробности — в соответствующей инженерной спецификации.
5. Включить изменения контекста в коммит выполненной задачи.

Не записывать сюда токены, настоящие данные жильцов или непроверенное утверждение «работает в MAX».
