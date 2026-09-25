# K00: стыки пула Катерины

Контракты и fake ports находятся в `src/dom_domych/agent/contracts.py` и
`src/dom_domych/agent/fakes.py`. После объединения A01 команды K используют
общий `TrustedContext` из `contracts/base.py` и `ToolResult` из
`contracts/tools.py`. `KToolHandlers` проверяет схему, capability и actor до
передачи команды fake port. Реальные обработчики ещё не подключены к PostgreSQL
или MAX.

## Команды и границы

| Port | Команды | Ответ |
|---|---|---|
| `CasePort` | `search`, `get`, `create`, `attach_message` | кандидаты с фактами и version; дело с version/source refs |
| `KnowledgePort` | `search` | source ID/revision/reviewed; rule ID и deadline origin только при наличии |
| `RequestPort` | `prepare`, `submit`, `get_status` | draft version и отдельные `prepared`, `submitted`, `registered` |

`TrustedContext` несёт house/actor/event/run, principal, mode и capabilities вне
аргументов модели.
Tool JSON schemas берутся из Pydantic `TOOL_INPUTS`: `case.search`, `case.create`,
`case.attach_message`, `knowledge.search`, `request.prepare`, `request.submit`,
`case.get` и `request.get_status`.
Списки разрешённых режимов, capabilities, effect и handler закрепляет runtime K03.

Запись должна проверить house, actor/capability, idempotency key, ожидаемую
версию и данные источников в краткой транзакции. Fake показывает форму и
несколько ограничений, но не служит заменой доменной политики и блокировок K08/K10.
`submit` означает отправку операции; регистрация возникает только от доверенного
`request.registered` с номером и временем.

## События продолжения

Тип `ContinuationEvent` содержит `poll.threshold_reached`, `poll.expired`,
`evidence.added`, `request.registered`, `request.status_changed`,
`request.deadline_reached`, `resolution.rejected`, `document.ready`.
`Continuation` несёт house/case/version/event/time. Потребитель повторно читает
дело; event payload не считается текущей версией после другого изменения.

## Оставшиеся интеграционные стыки

- Сопоставить K application command port с минимальным A01 `CasePort`/`RequestPort`
  для потребителей Z; production service должен реализовать оба назначения.
- Сверить `CaseKind` и состояния с инициативой Z; авария является срочным
  маршрутом проблемы, а не отдельным типом aggregate, если так решит общий contract.
- Согласовать общие ошибки и сериализацию `source_refs`, operation IDs и внешних IDs.
- Утвердить право пользователя на `request.submit` и источник approval.

Проверки K00: `tests/agent/test_k00_contracts.py` и общие
`tests/contracts/test_core.py`, Ruff и mypy. Live G0 открыт.
