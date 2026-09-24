# 09. Предложение контрактов пула Замиры для G0

[Архитектура](02-architecture.md) · [Агент и tools](04-agent-and-tools.md) · [Данные](05-data-and-state.md) · [Задачи Замиры](../../context/tasks-zamira.md)

**Статус: предложение Z00; A01/K00 ещё не объединены.** Здесь описана граница модулей и проверяемые инварианты. Имена/поля общих Python DTO фиксируются только после A01. До этого файлы `contracts/` и базовые ports Алины не редактируются из пула Z.

## Базовые значения на стыке

- Внутренние IDs — UUID, внешние MAX IDs — точные целые/строковые представления без float; время — aware UTC. `house_id`, actor, principal/capabilities и correlation ID приходят из `TrustedContext`, который создаёт ingress/worker, а не аргументы LLM.
- `Scope` содержит `kind=house|entrance|floor|riser`; для этажа нужны подъезд и номер этажа, для стояка — явный `riser_id` и тип системы. Неизвестный подъезд/стояк требует уточнения, а не совпадения по номеру квартиры.
- `AudienceSnapshot` содержит `audience_id`, `house_id`, `criteria`, `criteria_revision`, `created_at`, список уникальных `resident_id`, отдельно `eligible_count` и `reachable_count`. Состав и denominator после открытия опроса неизменяемы; новая область создаёт новую revision с историей.
- `PolicySnapshot` содержит `kind`, `revision`, точные десятичные пороги, denominator, `opens_at`, `closes_at`, `subject_revision`, `demo`. Изменение политики не пересчитывает задним числом старый опрос.
- Ошибки кодируются явно (`NOT_ELIGIBLE`, `STALE_REVISION`, `POLL_CLOSED`, `WRONG_HOUSE`, `NO_AUDIENCE`, `CONFLICT`) и преобразуются в tool/transport ответ на границе. `expected_version` обязателен для изменения существующей сущности.

## Порты и доверенные источники

| Порт / владелец | Команды и результат | Проверка внутри use case |
|---|---|---|
| `HouseContextPort` / A → Z | `list_residencies(house_id)` или scoped query возвращает подтверждённые/неподтверждённые проживания, квартиру, подъезд, этаж, явные связи стояков и DM state | Z самостоятельно создаёт снимок подходящих **взрослых подтверждённых** жителей; A не подменяет eligible числом доставленных |
| `AudiencePort` / Z → K | `resolve(scope, trusted_context)` → snapshot ID, revision, eligible/reachable; `get(audience_id, house_id)` | Tenant filter, уникальность жителя, версионированный criterion; никакой scope из чужого дома |
| `PollPort` / Z → K/A | `open(case_id, audience_id, kind, subject_revision, policy, trusted_context)` → poll ID/deadline; `get_results(poll_id, house_id)` → tally/outcome; `record_answer(poll_id, actor_id, answer, source_event_id, received_at)` вызывается **только** из проверенного callback/message handler A | Actor реального события, membership snapshot, открытое окно и версия, один текущий ответ на жителя, история изменений; threshold event один раз |
| `CasePort` / K → Z | `create_initiative_case`, `get_case_snapshot`, `transition_case(expected_version, reason)` | K владеет общим `cases` и state machine; Z не пишет её таблицу напрямую |
| `InitiativePort` / Z → K | `create(case_id, wording, scope, author, expected_version)` → initiative revision; `revise` → новая revision и требование нового poll | Голоса прежней формулировки не переносятся молча; итог — позиция жителей, не ОСС |
| `DeliveryPort`, `JobPort` / A → Z | `enqueue_personal`, `enqueue_card`, `enqueue_deadline` в общей UoW; результаты delivery/job IDs | Намерение доставки и state атомарны; timeout MAX не меняет denominator и не считается успешной доставкой |
| `DocumentPort`, `FileStore` / Z → K/A | `prepare(case_id, document_kind, immutable_snapshot)` → document ID + queued; `get_ready` → file key/hash/template revision | Snapshot с case/poll/audience/rule revisions; рендер вне транзакции/event loop; A отправляет только готовый файл |
| `ExecutorPort` / Z → K | `submit(draft_id, operation_key, mode)` → operation ID; `get_status(request_id)` → status, source, registration time | В MVP `mode=demo`, служебное изменение только demo operator; prepared/PDF не равны registered |
| `ResolutionPort` / Z → K | `start_check(case_id, done_event, original_audience_id)` → poll ID; `finalize` → closed/reopened/unconfirmed event | `done` лишь начинает проверку, а закрытие возможно после результата исходной категории по frozen policy |

Сигнатуры в таблице описывают смысл команд, не публикуют несовместимый второй API. A01 оформит общий DTO/Protocol и contract tests; реализации Z останутся за пределами transport/ORM Алины и K.

## События и атомарность

`poll.threshold_reached`, `poll.expired`, `document.ready`, `request.registered`, `request.status_changed`, `resolution.rejected` — структурированные события с `event_id`, `house_id`, `case_id`, `entity_version`, `causation_id`, `occurred_at`. Event ID и operation key служат дедупликации, а не заменяют проверку состояния. LLM не получает `poll.answer` и не создаёт событие `request.registered` от имени исполнителя.

Одна короткая UoW сохраняет poll + audience reference + outbox + deadline, ответ + обновление версии + threshold event, либо итог результата + case transition + отмену будущих jobs. Внешняя сеть, LLM и PDF-рендер не выполняются внутри SQL-транзакции. После конфликта версий состояние перечитывается; старый job становится no-op.

## Независимые проверки до интеграции

Z использует fake `HouseContextPort`, `CasePort`, `DeliveryPort`, `JobPort` на [синтетическом доме Z02](../../context/tasks-zamira.md), затем сравнивает их contract tests с реализациями A/K. Чистые [правила Z01](../../src/dom_domych/domain/polls/policy.py) уже могут проверяться без общего пакета. PostgreSQL concurrency/migration tests, настоящий callback и MAX mobile/web относятся к G1–Release и не объявляются пройденными по fake.
