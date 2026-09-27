# Проверенное состояние проекта

Проверено 27.09.2026 по ветке `al-tasks`. Этот файл меняется после реализации задач; старое значение статуса не является вечной истиной.

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
| AudienceService Z03 | Частично: выбор проверен на fake, PostgreSQL snapshot/revision/idempotency и конкурентный successor — на локальной PostgreSQL 16 | `src/dom_domych/application/audiences/service.py`, `src/dom_domych/infrastructure/postgres/audiences.py`, `migrations/versions/63a9d1e4bc02_z03_audiences.py`, `tests/infrastructure/test_z03_audiences_postgres.py`; K runtime ещё не подключён |
| PollService Z04 | Частично: поведение проверено на fake; PostgreSQL ответы/история, конкурентный голос, deadline job и одно threshold event — на локальной PostgreSQL 16 | `src/dom_domych/infrastructure/postgres/polls.py`, `z_poll_models.py`, `migrations/versions/9d20b8a6c743_z04_polls.py`, `tests/infrastructure/test_z04_polls_postgres.py`; карточки/production callback и scheduler wiring ещё не подключены |
| Callback handler Z05 | Частично: token/actor/revision/expiry проверены на fake и MAX MockTransport → trusted actor → PostgreSQL PollRepository | `src/dom_domych/application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`; production process и выпуск кнопок не подключены |
| InitiativeService Z06 | Частично: K case/author reader и PostgreSQL UoW редакций/опросов с отзывом action tokens проверены локально | `infrastructure/postgres/initiative_cases.py`, `initiatives.py`, `z_initiative_models.py`, `migrations/versions/a7c41b0d55e8_z06_initiatives.py`, `tests/infrastructure/test_z06_initiatives_postgres.py`; доставка и общий runtime ещё не подключены |
| Публичные карточки Z07 | Частично: тексты/шкалы unit, текущий poll/initiative → A outbox/edit/coalescing проверен на локальной PostgreSQL 16 | `src/dom_domych/application/cards/production.py`, `tests/infrastructure/test_z07_cards_outbox.py`; живой MAX и голосующие кнопки не подключены |
| Напоминания и итог инициативы Z08 | Частично: частотный лимит, текущие права, outbox и supported/not_supported проверены на локальной PostgreSQL 16 | `src/dom_domych/infrastructure/postgres/initiative_followup.py`, `z_followup_models.py`, `migrations/versions/b3e68a179c02_z08_followup.py`, `tests/infrastructure/test_z08_followup_postgres.py`; K переход в исполнение и runtime job wiring ещё не подключены |
| FileStore и immutable snapshot Z09 | Частично: локальный FileStore и PostgreSQL queued snapshot/metadata проверены на локальной PostgreSQL 16 | `src/dom_domych/infrastructure/files/local.py`, `src/dom_domych/infrastructure/postgres/documents.py`, `z_document_models.py`, `migrations/versions/c9ad4420e123_z09_documents.py`, `tests/infrastructure/test_z09_documents_postgres.py`; PDF worker ещё не подключён |
| PDF-рендер Z10 | Частично: 4 шаблона проверены локально | `src/dom_domych/infrastructure/documents/renderer.py`, `tests/infrastructure/test_pdf_renderer.py`, 4 синтетических образца в `output/pdf/`; A08/A11 transport есть, durable PDF job и сквозная доставка не подключены |
| DemoExecutor Z11 | Частично: команда и переходы проверены на fake | `src/dom_domych/domain/executor/models.py`, `src/dom_domych/application/executor/service.py`, `tests/fakes/executor.py`, `tests/domain/test_demo_executor.py`; нет PostgreSQL repository/outbox и связи с K RequestService |
| Старт проверки результата Z12 | Частично: done → исходная аудитория/poll проверены на fake | `src/dom_domych/domain/resolution/models.py`, `src/dom_domych/application/resolution/service.py`, `tests/fakes/resolution.py`, `tests/domain/test_resolution_service.py`; нет K CasePort, PostgreSQL UoW и MAX-доставки |
| Итоги проверки результата Z13 | Частично: closed/reopened/unconfirmed проверены на fake | Те же файлы resolution; отдельный K production transition и отмена jobs ещё нужны |
| PDF QA Z15 | Частично: локально просмотрены 4 образца | `docs/release/zamira-pdf-qa.md`; mobile/web MAX и outbox ещё не проверены |
| Материалы Z16 | Частично: локальный handoff и воспроизведение PDF готовы | `docs/release/zamira-handoff.md`, `scripts/generate_zamira_demo_pdfs.py`; сквозной runbook ждёт A/K интеграции |
| Python-проект и зависимости A00 | Проверено локально | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; `uv sync --locked`, Ruff, mypy, 227 tests прошли; удалённый CI ещё не запускался |
| PostgreSQL core A02 | Проверено локально на PostgreSQL 17.8 + pgvector 0.8.1 | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`: единая migration/check, повторный seed, 227 тестов и сохранность head/vector/2 домов/20 проживаний после рестарта |
| HouseContextPort A05 | Частично: выборка и интеграция с Z AudienceService проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: приглашение, привязка MAX ID, DM `/start`, stopped и выбор дома проверены локально | `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, `tests/infrastructure/test_demo_enrollment.py`; выдача кодов реальным operator и live MAX ещё не подключены |
| MAX Bot API A03 | Частично: документированные методы проверены через MockTransport | `infrastructure/max/client.py`, `tests/infrastructure/test_max_client.py`; upload bytes добавлен в A11, реальный токен/бот не проверены |
| Webhook/inbox A04 | Частично: text/callback/attachment refs/deletion/lifecycle/membership/admin permissions и unknown Update, dedupe/durable insert проверены на PostgreSQL 18 | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`, `tests/infrastructure/test_max_webhook.py`; HTTPS/MAX smoke отсутствует |
| Inbox worker A07 | Частично: production loop собирает onboarding → K message/continuation handlers; lease/recovery/retry проверены на PostgreSQL 17 | `entrypoints/processes.py`, `application/agent/messages.py`, inbox/K14 tests; Z handlers ещё не подключены |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, DM, карточка/edit, недоступный адресат и отдельный process loop проверены на PostgreSQL 17 + MockTransport | `entrypoints/processes.py`, `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`; PDF upload добавлен в A11, реальный MAX отсутствует |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency, stale no-op и K revision adapter в production loop проверены на PostgreSQL 17 | `entrypoints/processes.py`, `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`; Z handlers/revisions ещё не подключены |
| MAX poll callbacks A10 | Частично: actor/дом/токен и ACK проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/poll_actions.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_max_poll_callback.py`; Z PollRepository и live MAX ещё не подключены |
| MAX files A11 | Частично: PDF upload, token reuse/retry, безопасное фото, process-local rate limits и coalescing edit реализованы | `infrastructure/max/media.py`, `infrastructure/max/evidence.py`, `infrastructure/max/rate_limit.py`, tests; live MAX mobile/web и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: полный Compose локально запускает и перезапускает migrate/API/inbox/scheduler/outbox/maintenance/Caddy; PG/FileStore volumes сохраняются, локальный HTTPS readiness различает БД и LLM; наружу опубликован только Caddy | `Dockerfile`, `deploy/compose.yml`, `entrypoints/api.py`, `entrypoints/processes.py`; публичный DNS/TLS, выбранная модель и live MAX/inference не проверены |
| Надёжность A13 | Частично: bounded retry/dead-letter/delivery_unknown, rate limits, coalescing и heartbeat outbox/jobs проверены | `infrastructure/max/rate_limit.py`, queue workers/repositories и PostgreSQL tests; live rate-limit и потеря прав MAX не проверены |
| Composition/polling A14 | Частично: process root запускает K inbox/scheduler, dev polling сохраняет batch до marker; отсутствующие Z ports явно fail | `entrypoints/processes.py`, `application/agent/composition.py`, process/config tests; Z repositories/callback/PDF jobs и G3 отсутствуют |
| Backup/restore A15 | Проверено локально на PostgreSQL 17.8/pgvector и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, retention tests; восстановлены head/vector, 2 дома/20 проживаний и 5 файлов с теми же SHA-256; временные данные удалены, DB restart пройден |
| MAX mobile/web A16 | Не проверено; подготовлен честный протокол | `docs/release/max-mobile-web-matrix.md`; нужен live бот, два клиента и общий G3 runtime |
| Release A17 | Частично: secret audit текущих файлов/истории прошёл, 41 installed package инвентаризирован, archive/evidence tool готов | `scripts/release_audit.py`, `docs/release/platform-operations.md`; лицензия самого `dom-domych` не выбрана, tag/image digests нельзя фиксировать до G3 |
| Агент K00–K04 | Частично: contracts, dataset, production K tool composition и durable continuation проверены с fake LLM | `src/dom_domych/agent/`, `application/agent/composition.py`, `tests/agent/`, `evals/`; live inference и общий process открыты |
| Хранение опросов | Не реализовано | Z domain/application и A core есть; PostgreSQL repository/migration и wiring отсутствуют |
| Рабочий стенд и внешние проверки | Частично | Целевой PG17/pgvector, production image и полный local Compose lifecycle проверены; доступ MAX/модели, публичный HTTPS, mobile/web и событийный G3 runtime не проверялись |

Эти строки описывают только осмотр репозитория. Они не доказывают отсутствие внешнего аккаунта или бота у команды. И наоборот, схема в Markdown не доказывает готовность реализации.

## Следующий шаг по утверждённому плану

K handlers и repositories теперь запускаются из A14 process root для inbox/scheduler.
Следующий блокирующий шаг — реализовать Z production repositories/producers и заменить явные
unavailable adapters; без них callback/PDF/result часть runtime не работает. Затем нужны
реальный MAX/LLM доступ, HTTPS smoke и G1–G3/mobile-web прогоны. Все 227 tests,
общая migration/check, повторный seed и backup/restore прошли на PostgreSQL 17.8 +
pgvector 0.8.1. Production image и полный Compose lifecycle также прошли: все process
services и локальный Caddy HTTPS поднялись после рестарта, а наружу не публиковались API/БД.
Live MAX/LLM, публичный TLS/DNS и событийный G3 runtime остаются внешними проверками.

## Как обновлять после задачи

1. Сверить `git status`, файлы и результаты подходящих проверок.
2. Обновить только затронутые строки, указав пути к реализации и точную степень проверки: «частично», «реализовано, не проверено» или «проверено».
3. Синхронизировать раздел «Что уже сделано» в [AGENTS.md](../AGENTS.md) и при необходимости вводную страницу [инженерных документов](../docs/engineering/README.md).
4. Сохранить важный новый выбор в [решениях](decisions.md), а подробности — в соответствующей инженерной спецификации.
5. Включить изменения контекста в коммит выполненной задачи.

Не записывать сюда токены, настоящие данные жильцов или непроверенное утверждение «работает в MAX».
