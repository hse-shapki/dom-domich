# K00: предложения стыков пула Катерины

Контракты и fake ports находятся в `src/dom_domych/agent/contracts.py` и
`src/dom_domych/agent/fakes.py`. Это временная реализация для согласования с A01;
общие `contracts/` и `domain/ports.py` остаются за Алиной. До A01 реальные
обработчики не подключены к agent runtime, PostgreSQL или MAX.

## Команды и границы

| Port | Команды | Ответ |
|---|---|---|
| `CasePort` | `search`, `get`, `create`, `attach_message` | кандидаты с фактами и version; дело с version/source refs |
| `KnowledgePort` | `search` | source ID/revision/reviewed; rule ID и deadline origin только при наличии |
| `RequestPort` | `prepare`, `submit`, `get_status` | draft version и отдельные `prepared`, `submitted`, `registered` |

`TrustedContext` несёт house/actor/event/run и capabilities вне аргументов модели.
Tool JSON schemas берутся из Pydantic `TOOL_INPUTS`: `case.search`, `case.create`,
`case.attach_message`, `knowledge.search`, `request.prepare`, `request.submit`.
`case.get` и `request.get_status` требуют отдельной команды при переносе в A01.
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

## Для согласования в A01

- Свести `TrustedContext` с общим trusted event, включая principal type,
  correlation ID, deadline и demo/live mode.
- Сверить `CaseKind` и состояния с инициативой Z; авария является срочным
  маршрутом проблемы, а не отдельным типом aggregate, если так решит общий contract.
- Согласовать общие ошибки и сериализацию `source_refs`, operation IDs и внешних IDs.
- Утвердить право пользователя на `request.submit` и источник approval.

Проверки K00: `tests/agent/test_k00_contracts.py`. Общие contract tests и mypy
после A00/A01 остаются отдельной интеграционной проверкой; live G0 открыт.
