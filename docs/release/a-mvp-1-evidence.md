# A-MVP-1 evidence — 30.09.2026

## Зафиксированная конфигурация

- Ветка: `a-mvp-1`; implementation commit:
  `b9de58fb4675e3b74522642d2d0ce517009954ad` (base `c79454168706682a6a1a909812da30cb7bf27dde`).
- Ingress: MAX long polling; активных webhook — `0`.
- PostgreSQL: `pgvector/pgvector:0.8.1-pg17`, image digest
  `sha256:3e8b3adfd27b5707128f60956f62a793c3c9326ea8cfaf0eab7adccb5d700b21`;
  Alembic head `0a7b6c5d4e3f`, pgvector `0.8.1`.
- Inference: host Ollama `0.32.1`, `qwen3:4b`, model digest
  `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- Собранный inbox image: `sha256:313955e1ee190d14466e4c2a327f79634a8ccef646111b0716a2ee8c6fd64754`.
  Это локальный image ID, не опубликованный registry digest.

## Фактически пройдено

Из чистого named volume Compose выполнил `migrate → seed → preflight`, после чего поднял
polling, inbox, scheduler, outbox, documents и maintenance. Redacted preflight из того же
stand подтвердил БД, миграцию, pgvector, MAX `/me`, отсутствие webhook и непустой ответ
`qwen3:4b`. После повторной сборки из implementation commit все workers снова стали healthy,
а данные live-прогона сохранились.

Подтверждённый demo-житель отправил обычные сообщения в связанной MAX-группе. В той же БД
зафиксированы два group `message.received` со статусом `done`, три завершённых agent run,
шесть успешных tool call (`knowledge.search`, `case.search`, `case.create`,
`case.attach_message`) и две outbox-доставки со статусом `sent` и реальными MAX message ID.
Тем самым критерий durable `MAX polling → inbox → agent/tools → outbox → MAX` пройден.
Сообщения участника до регистрации также попали в durable inbox, но не получили trusted actor
и ответа.

Проверки кода: Ruff, format check, mypy; clean migration до head; двойной seed; Alembic check;
`293 passed` на PostgreSQL 17/pgvector. Оба Compose profile (`polling`, `webhook`) проходят
`docker compose config`; secret audit текущего дерева вернул пустой список.

## Ограничения и следующий стык

- Ollama и Compose работают на Mac команды; при выключенном Mac бот недоступен.
- Публичный HTTPS webhook, mobile/web матрица и K15 model metrics этим прогоном не проверены.
- Созданное `problem.detected` дошло до durable inbox, но осталось без принимающего downstream
  handler. Это открытый application-стык Z-MVP-1 и блокер полного G3, а не сбой A-MVP-1
  transport/inference spine.
- Содержательная полезность текста ответа отдельно не оценивалась; статус `sent` означает
  подтверждённую Bot API доставку с message ID, но не ручную mobile/web QA.
