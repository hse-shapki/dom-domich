# 03. MAX: официальный API и адаптер проекта

[Навигация](README.md). Проверено по официальной документации 24.09.2026. Python-интеграция использует HTTPX и документированные методы MAX. Перед фиксацией клиента повторить smoke-test: API и схемы событий могут изменяться.

## 1. Внешний API MAX

Актуальная обзорная страница указывает `https://platform-api2.max.ru` и заголовок `Authorization: <access_token>`. Старый `platform-api.max.ru` из первоначального файла проекта не используем как актуальный default. Проверяем доверенную цепочку сертификатов, включая указанные MAX сертификаты Минцифры; TLS verification не отключаем. `GET /chats` отмечен устаревшим, а добавление участников через API ограничено и не нужно продукту. [Обзор Bot API](https://dev.max.ru/docs-api).

### Методы, которые нужны продукту

| Действие | Метод MAX | Наш вызывающий компонент |
|---|---|---|
| Проверить токен/бота | `GET /me` | Startup probe MaxAdapter |
| Настроить webhook | `POST /subscriptions` | Deployment task |
| Проверить подписки | `GET /subscriptions` | Health/operations |
| Получать события локально | `GET /updates` | Dev polling adapter |
| Написать в домовой чат | `POST /messages?chat_id=...` | Outbox Worker |
| Написать жителю | `POST /messages?user_id=...` | Outbox Worker |
| Обновить карточку | `PUT /messages?message_id=...` | Card Renderer / Outbox |
| Ответить на нажатие | `POST /answers?callback_id=...` | Callback handler / Outbox |
| Загрузить документ | `POST /uploads?type=file`, затем upload URL | Attachment adapter |

Ссылки методов: [messages](https://dev.max.ru/docs-api/methods/POST/messages), [редактирование](https://dev.max.ru/docs-api/methods/PUT/messages), [answers](https://dev.max.ru/docs-api/methods/POST/answers), [uploads](https://dev.max.ru/docs-api/methods/POST/uploads).

Это методы MAX, не endpoints нашего приложения. `case.create`, `poll.open`, `request.prepare` платформа не предоставляет: это наши tools и бизнес-сервисы.

## 2. Python-клиент и webhook

Реализуем `MaxApiClient` на `httpx.AsyncClient`: типизированные методы для сообщений, редактирования, callbacks, подписок и uploads. Pydantic DTO описывают нужные запросы и варианты Update; inline-клавиатура сериализуется в документированный JSON. Подписку регистрирует deployment-команда, события принимает FastAPI endpoint. MAX публикует OpenAPI-спецификацию; её можно использовать для сверки DTO или генерации клиента, но для выбранного подмножества ручек генератор не является обязательной зависимостью. [Официальный API и OpenAPI](https://dev.max.ru/docs-api).

Общий клиент переиспользует соединения, задаёт явные connect/read/write/pool timeouts и закрывается при shutdown. Long polling получает отдельный read timeout с запасом к времени ожидания MAX. Retry и rate limits контролирует outbox; не наслаиваем неограниченные повторы в HTTP-клиенте. [HTTPX async](https://www.python-httpx.org/async/).

Авторизационный заголовок MAX привязан к его API origin. Загрузку по выданному upload URL выполняет отдельный транспорт по документированному формату; нельзя автоматически пересылать секреты на произвольный host/redirect. Состояние диалогов хранится в PostgreSQL, не в памяти клиента.

Production-стенд принимает webhook по HTTPS на 443, с доверенным сертификатом. При создании подписки задаём secret, на входе сравниваем `X-Max-Bot-Api-Secret`. MAX требует ответ `200` в течение 30 секунд; наше правило — сохранять inbox и отвечать сразу, не ждать LLM. Если БД не приняла событие, не подтверждаем сохранение. [Webhook](https://dev.max.ru/docs-api/methods/POST/subscriptions).

Dev polling допускается только без активного webhook. Сохраняем полученные события перед продвижением marker; без marker возможна потеря предшествующих событий. Для событий группового чата боту нужны права администратора. [Long Polling](https://dev.max.ru/docs-api/methods/GET/updates).

На один токен выбираем один режим получения событий. Два разработчика не запускают независимые pollers на одном боте. Для параллельных треков — отдельные тестовые боты или общие записанные fixtures.

## 3. События и преобразование

| MAX Update | Внутреннее событие | Обработка |
|---|---|---|
| `bot_started` | `bot.started` | Транспортное событие; A06 запускает онбординг |
| `message_created` | `message.received` | Сохранение, контекст, агент |
| `message_callback` | `callback.received` | Проверка действия и участника, запись ответа без LLM |
| `message_edited` | `message.edited` | Новая ревизия, при необходимости пересмотр фактов |
| `message_removed` | `message.removed` | Отметка удаления и политика хранения; не считать старый текст новым подтверждением |
| `bot_added` / `bot_removed` | `house.bot_membership_changed` | Связь с разрешённым тестовым домом, остановка недоступных доставок |
| `bot_stopped` | `bot.stopped` | Транспортное событие; A06/A13 приостанавливают ЛС |
| `bot_admin_permissions_changed` | `house.bot_permissions_changed` | Проверка доступа к групповым событиям |

Источник списка: [Update](https://dev.max.ru/docs-api/objects/Update). Конкретные поля каждого варианта сверяем с официальной схемой и реальными fixtures. На входе — Pydantic discriminated union по `update_type`, неизвестный вариант сохраняем для диагностики и не исполняем как команду; у Update не предполагаем универсальный `update_id`.

Проектируем нормализованный envelope:

```text
event_id: наш UUID
source: max | scheduler | demo_executor
source_key: стабильный ключ дедупликации конкретного типа
event_type: внутренний тип
house_id: разрешённая связь чата/дела с домом
actor_id: внутренний resident либо доверенный system principal
external_message_id / callback_id: nullable
occurred_at / received_at
payload_version / payload
correlation_id / causation_id
```

Для нового сообщения ключ строится по bot/chat/message identity; для callback — по callback identity; для редактирования учитывается revision/timestamp/hash содержимого. Дедупликация транспорта и объединение похожих жалоб — разные операции. Python `int` сохраняет точность внешних ID; в PostgreSQL используем bigint, в LLM/tool DTO — строки, на границе Bot API — числовой формат по его schema. Не преобразуем ID через float.

## 4. Адресная личка

Онбординг команды: каждый тестовый житель открывает личный диалог с ботом, проходит привязку к квартире и получает проверочное сообщение. Отмечаем `dm_status=reachable|unknown|stopped|failed`.

Не предполагаем, что membership в групповом чате гарантирует возможность личной доставки. Это проверяется на реальных аккаунтах. При неуспехе не раскрываем квартиру или персональный ответ в общем чате; показываем общую инструкцию открыть бота и фиксируем недоставку. Состав подходящей аудитории не сокращаем до успешно уведомлённых.

Дом не берётся из произвольного текста пользователя или callback. При личном сообщении пользователя с несколькими привязками агент уточняет дом; для callback дом определяется сохранённым опросом.

## 5. Карточки, кнопки и идентификаторы

Используем `inline_keyboard` с короткими callback-кнопками. В payload — случайный непрозрачный `action_token`; серверная запись связывает его с action, poll, audience member, сроком и версией карточки. Не кладём персональные данные или полномочия в payload.

Чистый [handler Z05](../../src/dom_domych/application/polls/callback.py) проверяет серверную запись токена и вызывает PollService. A10 добавил `PostgresPollActionStore` (в БД только digest токена) и `MaxPollCallbackTransport`: он подтверждает callback через `POST /answers`, проверяет MAX actor по реестру подтверждённых совершеннолетних жильцов, привязку чата к дому и передаёт handler доверенный контекст. Локальные PostgreSQL/MockTransport tests проходят; wiring к production PollRepository и проверка кнопки в mobile/web MAX ещё нужны. Повтор callback с тем же событием должен отсеиваться inbox и PollRepository, а не по одноразовому использованию token: житель может поменять голос в рамках открытого окна.

Нажатие не доказывает право голоса: handler проверяет MAX actor, принадлежность snapshot аудитории и актуальность опроса. Для общих карточек токен может быть общий, но проверка права участника обязательна. Пересылка карточки не является механизмом распространения интерактивного интерфейса: документация указывает, что кнопки при пересылке не переносятся. [Клавиатура](https://dev.max.ru/docs-api/use-cases/sending-messages/keyboard).

Сохраняем `message_id` каждой карточки. Шкалу обновляем редактированием сообщения с coalescing: несколько быстрых голосов приводят к одному обновлению последней версии. [PUT messages](https://dev.max.ru/docs-api/methods/PUT/messages).

## 6. Доставка и файлы

- Ограничитель отправки: не более двух сообщений/секунду на диалог; длинный текст разбиваем по границе смысла с учётом ограничения 4000 символов. [POST messages](https://dev.max.ru/docs-api/methods/POST/messages).
- Ответы на callback имеют отдельное документированное ограничение; считаем их в лимитере. HTTP `200` проверяем вместе с `success`/телом результата, а не принимаем как безусловный успех. [POST answers](https://dev.max.ru/docs-api/methods/POST/answers).
- Общий ограничитель вызовов настраиваем не выше указанных MAX 30 rps. Upload: получить URL → загрузить один файл → сохранить token → отправить file attachment. На `attachment.not.ready` применяем ограниченный retry/backoff. [POST uploads](https://dev.max.ru/docs-api/methods/POST/uploads).
- Для timeout после отправки возможен неизвестный результат. Не обещаем exactly-once внешнюю доставку без поддержки платформы: сохраняем `delivery_unknown`, сверяем доступные данные и не повторяем бесконечно.
- Вложения скачивает отдельный адаптер только из допустимых источников с проверкой размера/MIME; пользовательский URL не становится произвольным HTTP tool агента.

## 7. Что перепроверить при подключении

1. Доступ команды к созданию бота и неизменяемый ник по условиям трека.
2. Подписку, API base URL и timeouts HTTPX-клиента, TLS и реальные события.
3. Callback, сообщение в группу и личку, PDF в mobile/web.
4. Права бота, остановку диалога и ошибки доставки.

Официальная страница создания сейчас допускает верифицированные профили юрлиц, ИП и самозанятых — старая фраза проекта «только юрлица» устарела. Фактический путь для студенческой команды выясняется отдельно, доступ не считается полученным. [Создание бота](https://dev.max.ru/docs/chatbots/bots-create/create).
