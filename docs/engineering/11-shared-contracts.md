# A01: общая граница треков

[Архитектура](02-architecture.md) · [Предложение Z00](09-z-interfaces.md) · [План](../../context/implementation-plan.md)

Контракты лежат в `src/dom_domych/contracts/` и `src/dom_domych/domain/ports/core.py`. Это минимальная граница для независимой разработки. Бизнес-команды остаются в use cases владельца и не превращаются в универсальный CRUD; при объединении ветки K00 сигнатуры сверяются contract tests, а несовместимое изменение публикуется отдельным коммитом.

| Контракт | Владелец реализации | Потребитель / назначение |
|---|---|---|
| `EventEnvelope`, `TrustedContext`, `ToolResult`, `ContractError` | A создаёт доверенное событие; K владеет tool runtime | Все треки; `house_id`, actor и capabilities не аргументы модели |
| `Clock`, `UnitOfWork`, `HouseContextPort` | A | K/Z; короткая транзакция, выборка проживаний по дому |
| `AudiencePort`, `PollPort`, `InitiativePort`, `DocumentPort`, `ResolutionPort`, `ExecutorPort`, `FileStore` | Z | K и A; IDs/версии/состояния и файлы, без доступа к чужой ORM |
| `CasePort`, `RequestPort`, `KnowledgePort` | K | A/Z; общее дело и обращение, house-scoped facts |
| `DeliveryPort`, `JobPort` | A | K/Z; `enqueue` означает сохранённое намерение, а не отправку/исполнение |

Для `DeliveryPort` adapter A08 — `PostgresDeliveryQueue(session, clock)`: передавайте ту же
`AsyncSession`, что и для изменения дела/опроса, затем один общий commit. Ключ операции уникален
внутри дома; повтор с другими данными отвергается. `recipient_id` указывает на жителя, которого
worker сопоставляет с подтверждённым проживанием и MAX user ID перед отправкой; недоступная личка
получает статус `unreachable` и не меняет размер аудитории. `chat_id` при enqueue сверяется с домом.
`edit_key` ссылается на `operation_key` уже отправленной карточки. `file_key` сохраняется, но до A11
остаётся в `waiting_attachment`. После сетевого timeout статус `delivery_unknown`: повтор без
проверки может продублировать сообщение; MAX не даёт этому adapter гарантии exactly-once.

Для `JobPort` adapter A09 — `PostgresJobQueue(session)` в той же UoW, что и изменение сущности.
`event_name` — значение `EventName` для события с entity payload, `due_at` — UTC,
`expected_version` — версия на момент постановки. `JobScheduler` после рестарта берёт due job по
lease, сверяет версию через `CurrentRevisionPort` K/Z и передаёт `EventEnvelope` в общий dispatcher.
Если версия уже иная или сущность удалена, job получает `skipped_stale`. Consumer также проверяет
версию под своим lock: между предварительной проверкой scheduler и use case возможна смена состояния.
Повтор того же `operation_key` безопасен только с теми же параметрами; иначе возвращается конфликт.

В коде портов `get` — минимальная читательская операция с обязательным `house_id`; она не заменяет специальные команды сервисов. Методы мутации проектируются вместе с владельцем и требуют `expected_version`, operation key и общей UoW. `RiserRef` и `ResidencyView` перемещены в общий pure-domain слой; типы Z импортируют тот же объект. Синтетический дом Z02 проверяется через `FakeHouseContext` в `tests/contracts/test_core.py`.

Нормализованный Event хранит внешние MAX ID строками без потери точности. `house_id=None` допустим до выбора дома в личке; tool context создаётся только после разрешения дома. Время в UTC, версии положительные, неизвестные поля строгих DTO отклоняются. `source` + `source_key` — ключ inbox дедупликации; уникальность обеспечит A04 на уровне БД.

Имена событий зафиксированы в `EventName`: вход сообщения/callback/вложения/удаления, `poll.threshold_reached`, `poll.expired`, `document.ready`, `request.registered`, `request.status_changed`, `resolution.rejected`, `job.due`. Разработчик нового события добавляет schema, producer/consumer и contract test. Успех `ToolResult` означает подтверждённый результат handler; отсутствие ошибки в LLM-ответе недостаточно.

Проверено локально: Pydantic round-trip/negative validation, совместимость fake реестра с выборкой Z, mypy и unit tests. Реальные K00-контракты из другой ветки, PostgreSQL, MAX и живой inference этой проверкой не подтверждены.
