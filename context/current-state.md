# Проверенное состояние проекта

Проверено 27.09.2026 по ветке `task_zamira`. Этот файл меняется после реализации задач; старое значение статуса не является вечной истиной. Раздел с K-фактами ниже описывает их собственные прежние прогоны; актуальные Z/A стыки указаны в таблице.

## Факты на дату проверки

После слияния `main` в `kae` K00 contracts используют общий A01
`TrustedContext`/`ToolResult`; девять schemas связаны с production K services
через единый tool registry. Z production ports теперь частично доступны в process root;
K initiative workflow пока не вызывает их автоматически; обычная проблема уже открывает
production audience/poll/card через durable event.
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
handler за успех. Production K handlers и вход из inbox подключены; ordinary problem
opening/outcome собраны через durable events, но initiative orchestration ещё открыта.
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
он не принимает author/house из аргументов модели. Z repository/UoW реализован
и проверен отдельно, но K agent route пока не создаёт инициативу автоматически.
K09: ProblemWorkflow проверяет scope дела и доверенный итог Z. Production handler
после `case.create` теперь одной UoW сохраняет frozen audience, poll, deadline,
переход case и публичную карточку/outbox; отсутствие group chat откатывает весь переход.
Trusted итог poll до agent continuation переводит дело в `request_ready` либо
`needs_evidence`; во второй ветке private outbox создаётся только для ответивших «да».
Следующий request/evidence цикл и live MAX пока не проверены.
K10: RequestService сверяет актуальную версию дела и проверенное правило,
хранит draft hash/version и явное согласование. Изменение черновика сбрасывает
approval, submit в demo идемпотентен через operation key, статус registered
появляется только от доверенного DemoOperation. Готовый документ теперь связывается
с request по `DocumentPort` с проверкой дома/case/hash/file key. Миграции и цикл
проверены на PostgreSQL 18 с fake Z ports. Production Z Document/Executor repositories
проверены отдельно; их стык с K процессом частично подключён.
K11: EmergencyService готовит draft сразу после проверки места и ответственного,
не зависит от poll; при пробеле в месте/источнике возвращает точное уточнение,
не выдумывает срок. Evidence intent идёт только в личный outbox, идемпотентен
на PostgreSQL 18. Use case опубликован как typed agent tool и собран с production
K services; fake route и PostgreSQL tests проходят. Production Z executor доступен
через process root; live MAX не проверен.
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
проверены на PostgreSQL 18; Z producers и handlers частично включены в общий
production worker, live inference не проверен.
K14: сквозная локальная проверка проходит от due job A через production K
composition и followup draft до сохранённого нового agent run на PostgreSQL 18
с fake LLM/Z ports. Повтор, устаревшая версия и чужой дом проверены; production
Z callback/PDF/result включены отдельно, но полный K/Z poll/PDF/MAX путь пока
не проверен из-за отсутствия orchestration и live сервисов.
Отдельно проверен путь нормализованного MAX message через durable inbox,
подтверждённое проживание, typed triage и production `case.create` до agent run
и reply outbox; реальный MAX при этом не использовался.
K15: оценщик traces считает маршруты, критические ошибки, источник, задержки
и tool calls по K01 dataset; unit-тесты проходят. Реальные метрики модели
не измерены: Qwen3-8B на 8 GiB Mac не дал ответа и вызвал swap. Версии и
ограничения записаны в `evals/k15-status.md` и K02 probe.
K16: четыре вариативных демо-пути, ссылки на проверяемые тесты и provenance
собраны в `docs/release/katerina-demo-handoff.md`; live MAX/G3 evidence не
заполнены. Z handoff обновлён для PostgreSQL-модулей и локального воспроизведения.

| Область | Состояние | Проверяемое основание |
|---|---|---|
| Продуктовая концепция и журнал решений | Есть документация | `IDEA.md`, `docs/backlog.md`, `docs/open-questions.md` |
| Техническая архитектура, ограничения, треки и приёмка | Есть проектная документация | `docs/engineering/README.md` и восемь документов в той же папке |
| Персональные пулы технических задач | Спланированы; A00–A13/A15–A17 и часть Z реализованы локально или частично | `context/implementation-plan.md`, `tasks-alina.md`, `tasks-katerina.md`, `tasks-zamira.md` |
| Корневые правила для агентов | Есть | `AGENTS.md` |
| Постоянный контекст | Есть | `context/README.md`, `decisions.md`, `product.md`, `engineering.md`, `current-state.md` |
| Чистые доменные правила опросов Z01 | Проверены на unit-уровне | `src/dom_domych/domain/polls/policy.py`, `tests/domain/test_poll_policy.py`: 23 теста |
| Общие контракты A01 / предложения K00/Z00 | Частично: DTO/ports и registry совместимы; problem open/outcome связан, initiative route ещё нет | `src/dom_domych/contracts/`, `application/cases/production.py`, `application/agent/composition.py`, K/Z tests |
| Синтетический дом Z02 | Проверен как fixture и seed A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`, `scripts/seed_demo_house.py`: 4 fixture-теста |
| AudienceService Z03 | Частично: выбор проверен на fake, PostgreSQL snapshot/revision/idempotency и конкурентный successor — на локальной PostgreSQL 16 | `src/dom_domych/application/audiences/service.py`, `src/dom_domych/infrastructure/postgres/audiences.py`, `migrations/versions/63a9d1e4bc02_z03_audiences.py`, `tests/infrastructure/test_z03_audiences_postgres.py`; K runtime ещё не подключён |
| PollService Z04 | Частично: PostgreSQL ответы/история, конкурентный голос, deadline job и threshold event проверены на PostgreSQL 16; callback/cards/scheduler подключены | `src/dom_domych/infrastructure/postgres/polls.py`, `z_poll_models.py`, `migrations/versions/9d20b8a6c743_z04_polls.py`, `tests/infrastructure/test_z04_polls_postgres.py`; K route и live MAX не проверены |
| Callback handler Z05 | Частично: token/actor/revision/expiry и MAX MockTransport → trusted actor → PostgreSQL PollRepository проверены; production inbox и выпуск кнопок подключены | `src/dom_domych/application/polls/production.py`, `application/cards/production.py`, `entrypoints/processes.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`; live MAX не проверен |
| InitiativeService Z06 | Частично: K case/author reader и PostgreSQL UoW редакций/опросов с отзывом action tokens проверены локально | `infrastructure/postgres/initiative_cases.py`, `initiatives.py`, `z_initiative_models.py`, `migrations/versions/a7c41b0d55e8_z06_initiatives.py`, `tests/infrastructure/test_z06_initiatives_postgres.py`; доставка и общий runtime ещё не подключены |
| Публичные карточки Z07 | Частично: тексты/шкалы, текущий poll/initiative → outbox/edit/coalescing с callback-кнопками проверены на PostgreSQL 16 и MockTransport | `src/dom_domych/application/cards/production.py`, `migrations/versions/0a7b6c5d4e3f_z07_card_buttons.py`, `tests/infrastructure/test_z07_cards_outbox.py`; автоматический вызов из K workflow и live MAX не проверены |
| Напоминания и итог инициативы Z08 | Частично: два durable job при открытии, частотный лимит, текущие права, outbox и supported/not_supported проверены на PostgreSQL 16; DOMAIN poll expiry и reminder handler подключены к process root | `src/dom_domych/infrastructure/postgres/initiatives.py`, `initiative_followup.py`, `application/resolution/production.py`, `tests/infrastructure/test_z08_followup_postgres.py`; K переход в исполнение отсутствует |
| FileStore и immutable snapshot Z09 | Частично: локальный FileStore и PostgreSQL snapshot/metadata/idempotency проверены на локальной PostgreSQL 16; worker читает только frozen bytes | `src/dom_domych/infrastructure/files/local.py`, `src/dom_domych/infrastructure/postgres/documents.py`, `z_document_models.py`, `migrations/versions/c9ad4420e123_z09_documents.py`, `tests/infrastructure/test_z09_documents_postgres.py` |
| PDF-рендер Z10 | Частично: 4 шаблона проверены; PostgreSQL lease/recovery и bounded retry → process pool → FileStore → приватный outbox проверены на локальной PostgreSQL 16; отдельный Compose process подключён | `src/dom_domych/application/documents/worker.py`, `entrypoints/processes.py`, `deploy/compose.yml`, `tests/infrastructure/test_z09_documents_postgres.py`; live MAX ещё не проверен |
| DemoExecutor Z11 | Частично: PostgreSQL idempotency/конкуренция, approved draft, права, события/outbox и K регистрацию проверены на локальной PostgreSQL 16; K/A process root подключён | `src/dom_domych/infrastructure/postgres/demo_executor.py`, `application/executor/production.py`, `application/resolution/production.py`, `entrypoints/processes.py`, `tests/infrastructure/test_z11_demo_executor_postgres.py`; live MAX ещё не проверен |
| Старт проверки результата Z12 | Частично: trusted done → исходная аудитория/poll/jobs/outbox с личными кнопками и `checking_resolution` проверены на PostgreSQL 16; inbox handler подключён | `src/dom_domych/infrastructure/postgres/resolution.py`, `application/resolution/production.py`, `tests/infrastructure/test_z12_resolution_postgres.py`; live MAX ещё не проверен |
| Итоги проверки результата Z13 | Частично: три исхода, case event, pending jobs и `resolution.rejected` проверены на локальной PostgreSQL 16; scheduler/DOMAIN handler подключён | Те же файлы resolution; полный G3/live MAX ещё не проверены |
| Сквозная проверка Z14 | Частично: PostgreSQL/MockTransport цепь карточка → callback → голос → edit, отдельные PDF/Executor/result сценарии и retry проверены | `tests/infrastructure/test_z07_cards_outbox.py`, `test_z09_documents_postgres.py`, `test_z11_demo_executor_postgres.py`, `test_z12_resolution_postgres.py`; единый K/Z G3 и live MAX отсутствуют |
| PDF QA Z15 | Частично: 4 образца, все 7 страниц, hash и локальный PostgreSQL/FileStore/outbox путь проверены | `docs/release/zamira-pdf-qa.md`, `tests/infrastructure/test_z09_documents_postgres.py`; mobile/web MAX не проверены |
| Материалы Z16 | Частично: handoff, демо-политики, синтетические данные, обе развилки результата и воспроизведение PDF описаны | `docs/release/zamira-handoff.md`, `scripts/generate_zamira_demo_pdfs.py`; live G3 runbook ждёт K/Z orchestration и MAX |
| Python-проект и зависимости A00 | Проверено локально; предыдущий набор — GitHub Actions #26 | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; локально на целевом PG17/pgvector migration/check, двойной seed, Ruff, mypy и 247 тестов прошли; CI нового набора ожидается |
| PostgreSQL core A02 | Проверено локально на PostgreSQL 17.8 + pgvector 0.8.1 | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`: единая migration/check до `0a7b6c5d4e3f`, повторный seed и 247 тестов |
| HouseContextPort A05 | Частично: выборка и интеграция с Z AudienceService проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: operator CLI, приглашение, привязка MAX ID/чата, DM `/start`, stopped и выбор дома проверены на PostgreSQL 17 | `entrypoints/demo_operator.py`, `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, tests; CLI допускает только demo-дома, live MAX ещё не проверен |
| MAX Bot API A03 | Частично: документированные методы проверены через MockTransport | `infrastructure/max/client.py`, `tests/infrastructure/test_max_client.py`; upload bytes добавлен в A11, реальный токен/бот не проверены |
| Webhook/inbox A04 | Частично: text/callback/attachment refs/deletion/lifecycle/membership/admin permissions и unknown Update, dedupe/durable insert проверены на PostgreSQL 18 | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`, `tests/infrastructure/test_max_webhook.py`; HTTPS/MAX smoke отсутствует |
| Inbox worker A07 | Частично: production loop собирает onboarding → K message/continuation handlers; lease/recovery/retry проверены на PostgreSQL 17 | `entrypoints/processes.py`, `application/agent/messages.py`, inbox/K14 tests; Z handlers ещё не подключены |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, DM, карточка/edit, недоступный адресат и отдельный process loop проверены на PostgreSQL 17 + MockTransport | `entrypoints/processes.py`, `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`; PDF upload добавлен в A11, реальный MAX отсутствует |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency, stale no-op и K revision adapter в production loop проверены на PostgreSQL 17 | `entrypoints/processes.py`, `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`; Z handlers/revisions ещё не подключены |
| MAX poll callbacks A10 | Частично: actor/дом/токен и ACK проверены на PostgreSQL 18 + MockTransport | `infrastructure/postgres/poll_actions.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_max_poll_callback.py`; Z PollRepository и live MAX ещё не подключены |
| MAX files A11 | Частично: PDF upload, token reuse/retry, безопасное фото, process-local rate limits и coalescing edit реализованы | `infrastructure/max/media.py`, `infrastructure/max/evidence.py`, `infrastructure/max/rate_limit.py`, tests; live MAX mobile/web и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: полный Compose с Z document worker локально запускает и перезапускает migrate/API/inbox/scheduler/outbox/documents/maintenance/Caddy; локальный HTTPS readiness различает БД и LLM; наружу опубликован только Caddy | `Dockerfile`, `deploy/compose.yml`, `entrypoints/api.py`, `entrypoints/processes.py`; публичный DNS/TLS, выбранная модель и live MAX/inference не проверены |
| Надёжность A13 | Частично: bounded retry/dead-letter/delivery_unknown, rate limits, coalescing и heartbeat outbox/jobs проверены | `infrastructure/max/rate_limit.py`, queue workers/repositories и PostgreSQL tests; live rate-limit и потеря прав MAX не проверены |
| Composition/polling A14 | Частично: обычная проблема проходит durable open/outcome events → атомарные audience/poll/deadline/case/card-outbox и request_ready/needs_evidence; остальные runtime handlers подключены | `application/cases/production.py`, `entrypoints/processes.py`, `tests/infrastructure/test_problem_runtime.py`; initiative route и live G3 не готовы |
| Backup/restore A15 | Проверено локально на PostgreSQL 17.8/pgvector и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, retention tests; восстановлены Z head `0a7b6c5d4e3f`, vector, 40 public tables и 5 файлов с теми же SHA-256; временные данные удалены |
| MAX mobile/web A16 | Не проверено; подготовлен честный протокол | `docs/release/max-mobile-web-matrix.md`; нужен live бот, два клиента и общий G3 runtime |
| Release A17 | Частично: secret audit текущих файлов/истории прошёл, 41 installed package инвентаризирован, archive/evidence tool готов | `scripts/release_audit.py`, `docs/release/platform-operations.md`; лицензия самого `dom-domych` не выбрана, tag/image digests нельзя фиксировать до G3 |
| Агент K00–K04 | Частично: contracts, dataset, production K tool composition и durable continuation проверены с fake LLM | `src/dom_domych/agent/`, `application/agent/composition.py`, `tests/agent/`, `evals/`; live inference и общий process открыты |
| Хранение опросов | Частично: PostgreSQL repository/migration, callback и jobs проверены локально | `infrastructure/postgres/polls.py`, `application/polls/production.py`, `tests/infrastructure/test_z04_polls_postgres.py`; K route/live MAX не проверены |
| Рабочий стенд и внешние проверки | Частично | Целевой PG17/pgvector, production image и полный local Compose lifecycle проверены; доступ MAX/модели, публичный HTTPS, mobile/web и событийный G3 runtime не проверялись |

Эти строки описывают только осмотр репозитория. Они не доказывают отсутствие внешнего аккаунта или бота у команды. И наоборот, схема в Markdown не доказывает готовность реализации.

## Следующий шаг по утверждённому плану

K/Z handlers и repositories запускаются из A14 process root; обычная проблема уже
открывает audience/poll/card атомарно и применяет trusted outcome через durable inbox.
Следующий блокирующий шаг — собрать initiative route и переход поддержанной инициативы
к исполнению. Затем нужны реальный MAX/LLM
доступ, HTTPS smoke и G1–G3/mobile-web прогоны. На отдельной PostgreSQL 17.8 +
pgvector 0.8.1 с полной миграцией с нуля прошли 247 тестов, Ruff, mypy и Alembic
check без новых операций; тот же набор ранее прошёл на PostgreSQL 16. Старое
предупреждение Alembic о неизвестном типе `vector` сохраняется. A-пул повторно
проверил полный Compose lifecycle уже с Z document worker и восстановление нового
Z head. CI workflow поднимает тот же PG17/pgvector; GitHub Actions #26 на `c51ec86`
завершился успешно 27.09.2026.

## Как обновлять после задачи

1. Сверить `git status`, файлы и результаты подходящих проверок.
2. Обновить только затронутые строки, указав пути к реализации и точную степень проверки: «частично», «реализовано, не проверено» или «проверено».
3. Синхронизировать раздел «Что уже сделано» в [AGENTS.md](../AGENTS.md) и при необходимости вводную страницу [инженерных документов](../docs/engineering/README.md).
4. Сохранить важный новый выбор в [решениях](decisions.md), а подробности — в соответствующей инженерной спецификации.
5. Включить изменения контекста в коммит выполненной задачи.

Не записывать сюда токены, настоящие данные жильцов или непроверенное утверждение «работает в MAX».
