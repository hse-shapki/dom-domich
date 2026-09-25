# Эксплуатация платформы A12–A17

## Развёртывание

1. Скопировать `.env.example` в `.env` вне Git и задать `POSTGRES_PASSWORD`, production
   `DATABASE_URL`, `MAX_BOT_TOKEN`, `MAX_WEBHOOK_SECRET`, `PUBLIC_HOST`.
2. Проверить `docker compose -f deploy/compose.yml config`, затем собрать образы без `latest`.
3. Запустить `docker compose -f deploy/compose.yml up -d --build`. Одноразовый `migrate`
   применяет единственную Alembic history до старта API/outbox.
4. Проверить `/health/live` и `/health/ready`, затем отдельно зарегистрировать MAX webhook на
   `https://<PUBLIC_HOST>/webhook/max` с тем же secret.

Наружу опубликованы только 80/443 Caddy. PostgreSQL и процессы находятся во внутренней сети,
данные БД, Caddy и FileStore — в named volumes. API и outbox корректно закрывают HTTP clients и
SQLAlchemy engine при SIGTERM. Текущий compose не запускает inbox/scheduler: production handlers
K/Z и их repositories отсутствуют в этой ветке, поэтому фиктивно подтверждать события нельзя.

Dev polling запускается только с `MAX_INGRESS_MODE=polling` командой
`dom-domych-process polling`; API factory при этом отказывает в старте. Marker продвигается только
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

## Перед релизом

- Выполнить locked install, Ruff, mypy, pytest и миграцию пустой PostgreSQL 17/pgvector.
- Записать digest каждого реально собранного/pulled image через `docker image inspect`; теги в
  Compose не являются digest.
- Заполнить фактическую mobile/web матрицу с датой, версиями клиентов и commit. Пустые результаты
  не заменять галочками.
- Проверить `git status`, `git diff --check`, tracked files и всю историю на secrets/личные данные.
- Повторить транзитивный license audit, сохранить NOTICE, revisions моделей/prompts/config.
- Только после общего G3 создать сдаваемый commit, immutable tag и архив; записать SHA-256 архива.
