# A03: статус тонкого MAX Bot API клиента

[MAX integration](03-max-integration.md) · [A03](../../context/tasks-alina.md)

`MaxApiClient` реализует `GET /me`, `POST /messages`, `PUT /messages`, `POST /answers`, запрос upload slot `POST /uploads` и регистрацию webhook `POST /subscriptions`. Клиент использует `https://platform-api2.max.ru`, токен передаётся в `Authorization`, не в query; у редактирования/ack/subscription проверяет `success=true`, у отправки — `message.body.mid`. Внешние числовые ID не проходят через float. HTTPX session создаётся/закрывается вызывающим lifespan.

Контракты сверены 25.09.2026 с официальными страницами [обзора Bot API](https://dev.max.ru/docs-api), [сообщений](https://dev.max.ru/docs-api/methods/POST/messages), [callback acknowledgement](https://dev.max.ru/docs-api/methods/POST/answers), [uploads](https://dev.max.ru/docs-api/methods/POST/uploads) и [webhook](https://dev.max.ru/docs-api/methods/POST/subscriptions). MockTransport проверяет адресата, заголовок, точный ID и ошибку при HTTP 200 с `success=false`.

Это частичная A03: нет фактического доступа к боту и тестовому чату, живой `/me` и send/edit/callback/upload smoke не выполнены. A11 отдельно реализовал физическую загрузку PDF по выданному URL с ограничениями host/redirect/size и повтором `attachment.not.ready`; этот путь проверен только через MockTransport. Для G1/G2 остаётся проверить реальный MAX в мобильном и веб-клиенте.
