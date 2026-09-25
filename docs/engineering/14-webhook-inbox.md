# A04: MAX webhook и durable inbox

[MAX](03-max-integration.md) · [События](11-shared-contracts.md) · [PostgreSQL](12-postgres-core.md)

FastAPI `/webhook/max` сравнивает `X-Max-Bot-Api-Secret`, ограничивает тело, валидирует Update по типу, сохраняет raw Update и нормализованный `EventEnvelope` в `inbox_events` одной короткой транзакцией. Только после commit возвращает 200. Уникальный `(source, source_key)` делает повторную доставку идемпотентной. Неизвестный `update_type` сохраняется со статусом `ignored` и не передаётся агенту. `/ready` проверяет БД; webhook не выполняет LLM/доменную работу.

Поля нормализации сверены с [официальной OpenAPI схемой MAX](https://github.com/max-messenger/api-schema/blob/main/schema.yaml) и [webhook описанием](https://dev.max.ru/docs-api/methods/POST/subscriptions). Реальный actor callback — `callback.user.user_id`, ID сообщения — `message.body.mid`; `callback.payload` остаётся непрозрачным action token. `house_id` остаётся пустым до разрешения чата/проживания worker. Для неизвестного MAX Update сохраняется raw и hash key; для edit ключ включает timestamp и hash, чтобы новая редакция не терялась.

Проверено 25.09.2026: ASGITransport + PostgreSQL 18/UTF8, неправильный secret → 401, повтор Update → одна строка, unknown Update → `ignored`, callback actor не берётся из payload. Миграция применена и `alembic check` чист. Внешний HTTPS endpoint, реальный бот и MAX mobile/web не проверены. A07 должен читать `pending` с lease и вызывать dispatcher; до этого сохранённые события не обрабатываются автоматически. Срок хранения raw персональных сообщений задаётся в A15.
