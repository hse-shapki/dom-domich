# Эксплуатация платформы A12–A17

## Развёртывание

1. Скопировать `.env.example` в `.env` вне Git и задать `POSTGRES_PASSWORD`, production
   `DATABASE_URL`, `MAX_BOT_TOKEN`, `MAX_WEBHOOK_SECRET`, `PUBLIC_HOST`, а также доступные
   контейнерам `LLM_BASE_URL` и `LLM_MODEL`. Образ/веса модели в Compose не зафиксированы,
   пока K15 не выбрал прошедшую evals модель; endpoint поднимается отдельно или override-файлом.
2. Проверить `docker compose -f deploy/compose.yml config`, затем собрать образы без `latest`.
3. Запустить `docker compose -f deploy/compose.yml up -d --build`. Одноразовый `migrate`
   применяет единственную Alembic history до старта API/outbox/maintenance.
4. Проверить `/health/live` и `/health/ready`. Readiness возвращает `503`, если недоступна БД;
   при доступной БД и недоступном inference возвращает HTTP 200 со статусом `degraded`, чтобы
   ingress продолжал надёжно принимать события. Затем отдельно зарегистрировать MAX webhook на
   `https://<PUBLIC_HOST>/webhook/max` с тем же secret.

Операционные команды не печатают токен/secret:

```bash
uv run python -m scripts.max_operations probe
uv run python -m scripts.max_operations subscriptions
uv run python -m scripts.max_operations register \
  --url "https://<PUBLIC_HOST>/webhook/max" \
  --update-type message_created --update-type message_callback --update-type bot_started
```

Наружу опубликованы только 80/443 Caddy. PostgreSQL и процессы находятся во внутренней сети,
данные БД, Caddy и FileStore — в named volumes. API, inbox, scheduler, outbox и retention
maintenance корректно закрывают HTTP clients и SQLAlchemy engine при SIGTERM. Maintenance раз в
час идемпотентно удаляет просроченные файлы и редактирует payload завершённых inbox/outbox по
`PAYLOAD_RETENTION_DAYS`. Inbox регистрирует onboarding перед K message handler, затем K
continuation handlers; scheduler использует тот же dispatcher и K revision reader. Пока
отсутствуют production Z executor/document repositories, соответствующие события явно
завершаются ошибкой и проходят bounded retry/dead-letter, а не подтверждаются fake-результатом.
Poll callbacks, PDF jobs и полный G3 runtime остаются открыты.

Dev polling запускается только с `MAX_INGRESS_MODE=polling` командой
`dom-domych-process polling`; API factory при этом отказывает в старте, а poller проверяет через
`GET /subscriptions`, что активного webhook действительно нет. Marker продвигается только
после commit всей полученной пачки; после рестарта возможна повторная загрузка, которую гасит
уникальный inbox key.

## Backup и проверка восстановления

На остановленном для записи тестовом стенде выполнить:

```bash
uv run python -m scripts.runtime_backup backup \
  --database-url "$DATABASE_URL" --file-store "$FILE_STORE_DIR" \
  --output "backups/$(date -u +%Y%m%dT%H%M%SZ)"
uv run python -m scripts.runtime_backup verify --backup backups/<timestamp>
```

Restore намеренно разрешён только в заранее созданную пустую БД с именем `*_restore_test` и
пустой каталог FileStore. Это не команда восстановления поверх рабочего стенда:

```bash
uv run python -m scripts.runtime_backup restore \
  --database-url "$RESTORE_TEST_DATABASE_URL" --backup backups/<timestamp> \
  --file-store /tmp/dom-domych-restore-files
uv run alembic current
```

После восстановления проверить чтение одного PDF/evidence через FileStore, checksum, inbox lease
recovery и `/health/ready`. Отсутствующий файл должен давать `StoredFileNotFound` или
`FileIntegrityError`, а не успешную доставку.

25.09.2026 локальный restore smoke выполнен на PostgreSQL 18: восстановлены Alembic head
`e17d65a0f2c8`, 2 дома, 20 проживаний и PDF из FileStore с исходным SHA-256. Обе временные БД и
временный каталог после проверки удалены. Это не заменяет container-volume restart на PG17.

## Перед релизом

- Выполнить locked install, Ruff, mypy, pytest и миграцию пустой PostgreSQL 17/pgvector.
- Записать digest каждого реально собранного/pulled image через `docker image inspect`; теги в
  Compose не являются digest.
- Заполнить фактическую mobile/web матрицу с датой, версиями клиентов и commit. Пустые результаты
  не заменять галочками.
- Проверить `git status`, `git diff --check`, tracked files и всю историю на secrets/личные данные.
- Повторить транзитивный license audit, сохранить NOTICE, revisions моделей/prompts/config.
- Только после общего G3 создать сдаваемый commit, immutable tag и архив; записать SHA-256 архива.

Воспроизводимые команды аудита:

```bash
uv run python -m scripts.release_audit secrets
uv run python -m scripts.release_audit licenses --output /tmp/dom-domych-licenses.json
uv run python -m scripts.release_audit evidence --output /tmp/release-evidence \
  --image app=sha256:<64-hex> --image postgres=sha256:<64-hex> \
  --image caddy=sha256:<64-hex>
```

`evidence` требует чистое дерево и сам не создаёт/не двигает tag. На текущем lock audit нашёл 41
installed distribution; лицензии 40 внешних пакетов определены из metadata/classifiers. Для самого
проекта лицензия ещё не выбрана командой, поэтому финальный NOTICE пока нельзя считать готовым.
