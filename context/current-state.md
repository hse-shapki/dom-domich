# Проверенное состояние проекта

Проверено 30.09.2026 по ветке `main`. Этот файл меняется после реализации задач; старое значение статуса не является вечной истиной. Раздел с K-фактами ниже описывает их собственные прежние прогоны; актуальные Z/A стыки указаны в таблице.

## Факты на дату проверки

После слияния `main` в `kae` K00 contracts используют общий A01
`TrustedContext`/`ToolResult`; девять schemas связаны с production K services
через единый tool registry. Z production ports теперь частично доступны в process root;
K initiative workflow пока не вызывает их автоматически; обычная проблема уже открывает
production audience/poll/card через durable event.
K01: подготовлен русский набор из 24 синтетических кейсов и нулевой baseline
в `evals/`; прогон реальной модели пока не выполнен.
K02: `LlmPort`/fake/retry, OpenAI-compatible и нативный Ollama HTTPX adapters
проверены MockTransport. Старый Qwen3-8B probe на 8 GiB не удался; повторная
проверка `qwen2.5-coder:7b` дала только ограниченный одиночный tool round-trip.
30.09.2026 локальный Ollama `qwen3:4b` (digest `359d7dd4bcda`) через `/api/chat`
прошёл production-подобный путь на PostgreSQL: русский problem triage,
`case.search`, `case.create`, завершённый run и reply outbox. Это не MAX/G3 и
не оценка качества: полные K01/K15 evals, p50/p95 и release-выбор модели не выполнены.
K03: runtime проверяет allowlist, JSON schema, режим, capability и бюджет;
служебные `source_message_id`/`message_id` и operation IDs скрыты от модели и
детерминированно подставляются backend из доверенного event/run;
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
в сообщении проверены fake tests. Для локальных моделей допускается пояснение
только перед одним завершающим JSON-объектом; trailing text и неверная schema
отклоняются. Срочные выражения имеют консервативный
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
K09 evidence assessment теперь требует отдельной capability, текущей версии дела и
ссылки на сохранённое evidence того же дома. Решение и источники сохраняются в
versioned case event; повтор команды идемпотентен, статус дела не меняется от одного
фото или оценки. Проверено на мигрированной PostgreSQL 16; адресная привязка
входящего MAX-фото к делу, следующий request/evidence цикл и live MAX ещё не проверены.
K10: RequestService сверяет актуальную версию дела и проверенное правило,
хранит draft hash/version и явное согласование. Изменение черновика сбрасывает
approval, submit в demo идемпотентен через operation key, статус registered
появляется только от доверенного DemoOperation. Готовый документ теперь связывается
с request по `DocumentPort` с проверкой дома/case/hash/file key. Миграции и цикл
проверены на PostgreSQL 18 с fake Z ports. Для problem/initiative доверенное domain
`request.registered` теперь идемпотентно создаёт production appeal snapshot из сохранённых
case/request/poll/audience фактов; PDF worker и `document.ready` продолжают тот же процесс.
Emergency использует отдельный frozen audience без начального poll; live доставка ещё не покрыта.
K11: EmergencyService готовит draft сразу после проверки места и ответственного,
не зависит от poll; при пробеле в месте/источнике возвращает точное уточнение,
не выдумывает срок. Evidence intent идёт только в личный outbox, идемпотентен
на PostgreSQL 18. Use case опубликован как typed agent tool и собран с production
K services; fake route и PostgreSQL tests проходят. Production Z executor доступен
через process root. Durable `emergency.detected` отдельно фиксирует исходную аудиторию,
не меняя версию дела и не задерживая обращение; её используют appeal PDF и resolution.
Live MAX не проверен.
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
Дополнительный A14/G3 тест проводит обычную проблему через production audience/poll,
MAX callback/личный feedback/card edit, request approval/submit, demo registration/done,
resolution poll и оба исхода `closed`/`reopened`. Он использует реальные PostgreSQL
repositories/dispatcher и MockTransport ACK, рендерит frozen PDF в FileStore и связывает
`document.ready` с request; цельный live LLM/MAX upload/delivery он не проверяет.
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
| Общие контракты A01 / предложения K00/Z00 | Частично: problem open/outcome и initiative open/decision связаны; request после поддержки требует trusted actor/rule | contracts, production orchestration modules, K/Z tests |
| Синтетический дом Z02 | Проверен как fixture и seed A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`, `scripts/seed_demo_house.py`: 4 fixture-теста |
| AudienceService Z03 | Частично: выбор проверен на fake, PostgreSQL snapshot/revision/idempotency и конкурентный successor — на локальной PostgreSQL 16 | `src/dom_domych/application/audiences/service.py`, `src/dom_domych/infrastructure/postgres/audiences.py`, `migrations/versions/63a9d1e4bc02_z03_audiences.py`, `tests/infrastructure/test_z03_audiences_postgres.py`; K runtime ещё не подключён |
| PollService Z04 | Частично: PostgreSQL ответы/история, конкурентный голос, deadline job и threshold event проверены на PostgreSQL 16; callback/cards/scheduler подключены | `src/dom_domych/infrastructure/postgres/polls.py`, `z_poll_models.py`, `migrations/versions/9d20b8a6c743_z04_polls.py`, `tests/infrastructure/test_z04_polls_postgres.py`; K route и live MAX не проверены |
| Callback handler Z05 | Частично: 30.09.2026 PostgreSQL/MockTransport проверили атомарные голос + личный outbox + edit карточки, idempotency повторов, смену выбора, frozen audience, чужой дом, неизвестного actor/token, signed group ID, срок, закрытие и конкурентные callback; быстрый `POST /answers` остаётся после commit. Live callback вне аудитории ранее проверен, допустимый голос и отображение ЛС в web/mobile ещё нет | `src/dom_domych/application/polls/production.py`, `application/polls/max_callback.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py` |
| InitiativeService Z06 | Частично: durable opening создаёт frozen audience/revision/poll/reminders/card; decision переводит case в `request_ready`/`not_supported` вместе с history/outbox | initiative production/followup modules и tests; request требует подтверждённого actor и правила, live MAX отсутствует |
| Публичные карточки Z07 | Частично: 30.09.2026 callback автоматически создаёт edit в той же UoW, что и голос; смена выбора обратно к исходному счётчику корректно supersede-ит pending edit. PostgreSQL/MockTransport проверены; ранее live проблема открыла poll и доставила карточку в группу, live edit ещё не проверен | `src/dom_domych/application/cards/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`, `test_z07_cards_outbox.py` |
| Напоминания и итог инициативы Z08 | Частично: два durable job при открытии, частотный лимит, текущие права, outbox и supported/not_supported проверены на PostgreSQL 16; DOMAIN poll expiry и reminder handler подключены к process root | `src/dom_domych/infrastructure/postgres/initiatives.py`, `initiative_followup.py`, `application/resolution/production.py`, `tests/infrastructure/test_z08_followup_postgres.py`; K переход в исполнение отсутствует |
| FileStore и immutable snapshot Z09 | Частично: локальный FileStore и PostgreSQL snapshot/metadata/idempotency проверены на локальной PostgreSQL 16; worker читает только frozen bytes | `src/dom_domych/infrastructure/files/local.py`, `src/dom_domych/infrastructure/postgres/documents.py`, `z_document_models.py`, `migrations/versions/c9ad4420e123_z09_documents.py`, `tests/infrastructure/test_z09_documents_postgres.py` |
| PDF-рендер Z10 | Частично: 30.09.2026 четыре шаблона прошли единый локальный PostgreSQL/process pool → FileStore → приватный outbox → MAX upload/личный `POST /messages` MockTransport; lease/recovery покрыты прежними тестами. Live MAX download не проверен | `src/dom_domych/application/documents/worker.py`, `tests/infrastructure/test_z10_max_pdf_pipeline.py`, `test_z09_documents_postgres.py`; `docs/release/zamira-live-pdf-smoke.md` |
| DemoExecutor Z11 | Частично: PostgreSQL idempotency/конкуренция, права и события/outbox проверены; 30.09.2026 добавлен demo-only operator CLI register/done/list с replay и запретом live-дома, PostgreSQL-тест пройден. Live G3 не проверен | `src/dom_domych/infrastructure/postgres/demo_executor.py`, `entrypoints/zamira_operator.py`, `tests/infrastructure/test_z11_demo_executor_postgres.py`, `tests/entrypoints/test_zamira_operator.py` |
| Старт проверки результата Z12 | Частично: trusted done → исходная аудитория/poll/jobs/outbox с личными кнопками и `checking_resolution` проверены на PostgreSQL 16; inbox handler подключён | `src/dom_domych/infrastructure/postgres/resolution.py`, `application/resolution/production.py`, `tests/infrastructure/test_z12_resolution_postgres.py`; live MAX ещё не проверен |
| Итоги проверки результата Z13 | Частично: три исхода, case event, pending jobs и `resolution.rejected` проверены на локальной PostgreSQL 16; scheduler/DOMAIN handler подключён | Те же файлы resolution; полный G3/live MAX ещё не проверены |
| Сквозная проверка Z14 | Частично: 30.09.2026 единый локальный PostgreSQL/MockTransport problem → MAX callback → голос/card edit → request/PDF/FileStore/binding → demo executor → result poll → closed/reopened пройден; полный live MAX/LLM G3 остаётся открытым | `tests/infrastructure/test_g3_runtime.py`, `test_z10_max_pdf_pipeline.py` |
| PDF QA Z15 | Частично: 4 образца/7 страниц ранее визуально просмотрены; 30.09.2026 локально проверены hash, PDF text, версия/демо-маркировка и приватная доставка четырёх файлов в MockTransport. Реальные файлы в MAX mobile/web не открывались | `docs/release/zamira-pdf-qa.md`, `zamira-live-pdf-smoke.md`, `tests/infrastructure/test_z10_max_pdf_pipeline.py` |
| Материалы Z16 | Частично: handoff, безопасный live PDF smoke и точный ручной demo-сценарий `closed`/`reopened` с demo-only CLI подготовлены 30.09.2026. Двухчасовая live-финализация, MAX mobile/web и полный G3 не проверены | `docs/release/zamira-handoff.md`, `zamira-manual-demo.md`, `zamira-live-pdf-smoke.md`, `src/dom_domych/entrypoints/zamira_operator.py` |
| Python-проект и зависимости A00 | Проверено локально; GitHub Actions #50 для предыдущего набора | `pyproject.toml`, `uv.lock`, `.python-version`, `.github/workflows/python.yml`; на целевом PG17/pgvector 275 тестов, объединённый набор: 278 тестов, Ruff, mypy и Alembic check на чистой PG16.13 |
| PostgreSQL core A02 | Проверено локально на PostgreSQL 17.8 + pgvector 0.8.1 для предыдущего набора | `migrations/`, `infrastructure/postgres/`, `scripts/seed_demo_house.py`: единая migration/check до `0a7b6c5d4e3f` и 275 тестов на чистой БД |
| HouseContextPort A05 | Частично: выборка и интеграция с Z AudienceService проверены на PostgreSQL 18 | `infrastructure/postgres/house_context.py`, `tests/infrastructure/test_house_context_postgres.py`; запись demo-проживания добавлена отдельно в A06 |
| Demo onboarding A06 | Частично: operator CLI, приглашение, signed int64 group chat ID, привязка MAX ID/чата, stopped и выбор дома проверены на PostgreSQL; реальные `/start <код>` и `bot_added` группы подтверждены | `entrypoints/demo_operator.py`, `application/residents/enrollment.py`, `infrastructure/postgres/enrollment.py`, `infrastructure/max/onboarding.py`, tests; mobile и несколько домов ещё не проверены |
| MAX Bot API A03 | Частично: документированные методы проверены через MockTransport; live `/me`, личная/групповая отправка, `POST /answers` и PDF upload — 29–30.09.2026; MAX TLS объединяет Mozilla/Russian roots и не использует ambient proxy | `infrastructure/max/client.py`, `infrastructure/max/tls.py`, tests; mobile ещё не проверен |
| Webhook/inbox A04 | Частично: все поддержанные Update, dedupe/durable insert проверены на PostgreSQL; live polling принял `bot_started` и `message_created` | `entrypoints/api.py`, `infrastructure/max/updates.py`, `infrastructure/postgres/inbox.py`, `tests/infrastructure/test_max_webhook.py`; публичный HTTPS webhook и прочие live-типы ещё не проверены |
| Inbox worker A07 | Частично: production loop собирает onboarding → K message/continuation handlers; lease/recovery/retry проверены на PostgreSQL 17 | `entrypoints/processes.py`, `application/agent/messages.py`, inbox/K14 tests; Z handlers ещё не подключены |
| DeliveryPort/outbox A08 | Частично: enqueue/rollback, signed group ID, DM, карточка/edit, недоступный адресат и отдельный process loop проверены на PostgreSQL 17 + MockTransport; durable DM, group message, карточка с кнопками, PDF и edit того же group message ID реально прошли MAX | `entrypoints/processes.py`, `infrastructure/postgres/delivery.py`, `application/notifications/worker.py`; визуальная mobile/web проверка и доменный edit Z-карточки ещё нужны |
| JobPort/scheduler A09 | Частично: дедлайны, idempotency, stale no-op и K revision adapter в production loop проверены на PostgreSQL 17 | `entrypoints/processes.py`, `infrastructure/postgres/jobs.py`, `application/jobs/scheduler.py`; Z handlers/revisions ещё не подключены |
| MAX poll callbacks A10 | Частично: actor/дом/токен, outcome-specific notification и Z PollRepository проверены на PostgreSQL + MockTransport; live callback группы принят и отказ вне frozen audience подтверждён без записи голоса, notification принят MAX | `infrastructure/postgres/poll_actions.py`, `application/polls/production.py`, `tests/infrastructure/test_z05_poll_callback_postgres.py`; live допустимый голос/edit ещё не проверены |
| MAX files A11 | Частично: synthetic PDF реально прошёл FileStore → upload → сохранение token → `attachment.not.ready` → bounded retry → приватную доставку и виден в web MAX; безопасное фото, rate limits и coalescing edit проверены локально | `infrastructure/max/media.py`, `infrastructure/max/tls.py`, `application/notifications/worker.py`, tests; открытие файла, mobile, документ Z и K evidence linkage ещё нужны |
| Deploy/runtime A12 | Частично: полный Compose с Z document worker локально запускает и перезапускает migrate/API/inbox/scheduler/outbox/documents/maintenance/Caddy; локальный HTTPS readiness различает БД и LLM; наружу опубликован только Caddy | `Dockerfile`, `deploy/compose.yml`, `entrypoints/api.py`, `entrypoints/processes.py`; публичный DNS/TLS, выбранная модель и live MAX/inference не проверены |
| Надёжность A13 | Частично: bounded retry/dead-letter/delivery_unknown, rate limits, coalescing и heartbeat outbox/jobs проверены; live PDF подтвердил dead после пяти transport errors и recovery после исправления TLS | `infrastructure/max/rate_limit.py`, queue workers/repositories и PostgreSQL tests; live rate-limit и потеря прав MAX не проверены |
| Composition/polling A14 | Частично: локальная production-цепь problem → request → PDF binding → demo executor → resolution → closed проверена; initiative/emergency handlers подключены | `tests/infrastructure/test_g3_runtime.py`; без LLM/MAX upload это не live G3 |
| Backup/restore A15 | Проверено локально на PostgreSQL 17.8/pgvector и FileStore | `scripts/runtime_backup.py`, `application/jobs/maintenance.py`, retention tests; восстановлены Z head `0a7b6c5d4e3f`, vector, 40 public tables и 5 файлов с теми же SHA-256; временные данные удалены |
| MAX mobile/web A16 | Не проверено; подготовлен честный протокол | `docs/release/max-mobile-web-matrix.md`; нужен live бот, два клиента и общий G3 runtime |
| Release A17 | Частично: secret audit текущих файлов/истории прошёл, 41 installed package инвентаризирован, archive/evidence tool готов, CI Actions закреплены по SHA актуальных релизов | `scripts/release_audit.py`, `.github/workflows/python.yml`, `docs/release/platform-operations.md`; лицензия самого `dom-domych` не выбрана, tag/image digests нельзя фиксировать до G3 |
| Агент K00–K04 | Частично: contracts, dataset, production K tool composition и durable continuation проверены; нативный Ollama `qwen3:4b` прошёл PostgreSQL problem path `case.search` → `case.create` → reply outbox | `src/dom_domych/agent/`, `infrastructure/llm/ollama.py`, `application/agent/composition.py`, tests/evals; полный live MAX/G3 и реальные метрики ещё открыты |
| Хранение опросов | Частично: PostgreSQL repository/migration, callback и jobs проверены локально | `infrastructure/postgres/polls.py`, `application/polls/production.py`, `tests/infrastructure/test_z04_polls_postgres.py`; K route/live MAX не проверены |
| Рабочий стенд и внешние проверки | Частично | Целевой PG17/pgvector, production image и полный local Compose lifecycle проверены; live MAX bot identity/polling/DM onboarding, group card, отказ callback вне аудитории и транспорт синтетического PDF пройдены, local-LLM problem path проверен отдельно; публичный HTTPS, mobile, допустимый голос/доменный edit/файлы Z и цельный live G3 ещё не проверены |

Эти строки описывают только осмотр репозитория. Они не доказывают отсутствие внешнего аккаунта или бота у команды. И наоборот, схема в Markdown не доказывает готовность реализации.

## Следующий шаг по утверждённому плану

K/Z handlers и repositories запускаются из A14 process root; обычная проблема уже
открывает audience/poll/card атомарно, применяет trusted outcome и после доверенной
регистрации ставит immutable appeal PDF в очередь через durable inbox.
Следующий внутренний шаг — провести подготовку request от поддержанной инициативы после
явного действия подтверждённого жителя и найденного проверенного правила. Затем нужны реальный MAX/LLM
доступ, HTTPS smoke и G1–G3/mobile-web прогоны. На отдельной PostgreSQL 17.8 +
pgvector 0.8.1 с полной миграцией с нуля ранее прошли 275 тестов, Ruff, mypy по `src` и Alembic
check без новых операций. На чистой PostgreSQL 16.13 30.09.2026 после Z05/Z07/Z10/Z14/Z16
прошли 278 тестов, Ruff, mypy по `src` и Alembic check; PG17 для этого нового набора ещё не повторён. Старое
предупреждение Alembic о неизвестном типе `vector` сохраняется. A-пул повторно
проверил полный Compose lifecycle уже с Z document worker и восстановление нового
Z head. CI workflow поднимает тот же PG17/pgvector; GitHub Actions #50 на `2c6af2b`
с 275 тестами завершился успешно 30.09.2026.

## Как обновлять после задачи

1. Сверить `git status`, файлы и результаты подходящих проверок.
2. Обновить только затронутые строки, указав пути к реализации и точную степень проверки: «частично», «реализовано, не проверено» или «проверено».
3. Синхронизировать раздел «Что уже сделано» в [AGENTS.md](../AGENTS.md) и при необходимости вводную страницу [инженерных документов](../docs/engineering/README.md).
4. Сохранить важный новый выбор в [решениях](decisions.md), а подробности — в соответствующей инженерной спецификации.
5. Включить изменения контекста в коммит выполненной задачи.

Не записывать сюда токены, настоящие данные жильцов или непроверенное утверждение «работает в MAX».
