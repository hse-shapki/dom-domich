# Эксплуатация платформы A12–A17

## A-MVP-1: единый demo-стенд

Локальный принимаемый режим — MAX long polling и Ollama на хосте. Веса не попадают в Git или
Docker image. Проверенная конфигурация 30.09.2026: base commit `c79454168706682a6a1a909812da30cb7bf27dde`,
Ollama `0.32.1`, модель `qwen3:4b` с digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`, PostgreSQL image
`pgvector/pgvector@sha256:3e8b3adfd27b5707128f60956f62a793c3c9326ea8cfaf0eab7adccb5d700b21`.
Это фиксация реально поднятого стенда, но не результат K15 evals и не доказательство качества модели.

1. Установить Ollama `0.32.1`, выполнить `ollama pull qwen3:4b` и оставить Ollama запущенным.
2. Скопировать `.env.example` в игнорируемый `.env`, заменить `POSTGRES_PASSWORD` и
   `MAX_BOT_TOKEN`. Не коммитить `.env`. Для macOS/Windows оставить
   `LLM_BASE_URL=http://host.docker.internal:11434`, `LLM_BACKEND=ollama`,
   `MAX_INGRESS_MODE=polling`; `DATABASE_URL` внутри Compose должен содержать host `postgres` и
   имя `dom_domych_demo`.
3. Убедиться, что у бота нет активного webhook, затем поднять весь stand одной командой:

```bash
docker compose --env-file .env -p dom-domych --profile polling \
  -f deploy/compose.yml up -d --build --wait
docker compose --env-file .env -p dom-domych --profile polling \
  -f deploy/compose.yml logs preflight
```

Одноразовые процессы `migrate`, затем `seed`, затем `preflight` обязаны завершиться кодом 0.
`preflight` печатает только redacted JSON и в том же Compose stand проверяет Alembic head,
pgvector, MAX `/me`, список webhook и реальный ответ выбранной модели. После seed стартуют
polling, inbox, scheduler, outbox, documents и maintenance. PostgreSQL остаётся только во
внутренней сети; app-контейнеры получают отдельный egress для MAX и Ollama.

Для публичного HTTPS вместо polling задать `MAX_INGRESS_MODE=webhook`, непустые
`MAX_WEBHOOK_SECRET`/`PUBLIC_HOST` и использовать `--profile webhook`. Затем зарегистрировать
`https://<PUBLIC_HOST>/webhook/max`. Одновременно polling и webhook не запускать.

Текущие фактические ограничения: Ollama работает на Mac, поэтому бот доступен, только пока Mac,
Ollama и Compose запущены; внешний TLS/webhook и mobile/web матрица этим smoke не проверены;
модель ещё не прошла K15 evals. Demo seed разрешён только для `dom_domych_test*` либо при явном
флаге для БД с именем `dom_domych_demo`.

Операционные команды не печатают токен/secret:

```bash
uv run python -m scripts.max_operations probe
uv run python -m scripts.max_operations subscriptions
uv run python -m scripts.max_operations register \
  --url "https://<PUBLIC_HOST>/webhook/max" \
  --update-type message_created --update-type message_callback --update-type bot_started
```

После очной проверки demo-жителя оператор выдаёт одноразовый код (это чувствительное значение,
его единственный раз печатает сама команда) и отдельно может связать заранее известный MAX chat ID:

```bash
dom-domych-demo-operator issue-invitation \
  --house-id <uuid> --residency-id <uuid> --adult-verified --ttl-hours 24
dom-domych-demo-operator bind-house-chat --house-id <uuid> --max-chat-id <digits>
```

Обе команды берут `DATABASE_URL` из окружения, не принимают пароль аргументом и отказывают для
домов без `demo=true`. Код нужно передать конкретному проверенному жителю вне общего чата; в БД
остаётся только SHA-256 digest.

Наружу опубликованы только 80/443 Caddy. PostgreSQL и процессы находятся во внутренней сети,
данные БД, Caddy и FileStore — в named volumes. API, inbox, scheduler, outbox и retention
maintenance корректно закрывают HTTP clients и SQLAlchemy engine при SIGTERM. Maintenance раз в
час идемпотентно удаляет просроченные файлы и редактирует payload завершённых inbox/outbox по
`PAYLOAD_RETENTION_DAYS`. Inbox регистрирует onboarding перед K message handler, затем K
continuation handlers; scheduler использует тот же dispatcher и K/Z revision readers.
Production Z executor/document ports, callbacks, resolution handlers и отдельный PDF worker
подключены. Автоматический K/Z poll/initiative route и полный live G3 runtime остаются открыты.

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

27.09.2026 локальный restore smoke повторён на PostgreSQL 17.8 + pgvector 0.8.1:
в отдельную пустую БД восстановлены Alembic head `e4a29c371f62`, расширение vector,
2 дома, 20 проживаний и пять файлов из FileStore с исходными SHA-256. После рестарта
исходного контейнера БД сохранила head, расширение и строки. Временная restore-БД и каталог
удалены. Этот standalone restore сам по себе не проверяет production Compose volumes.

В тот же день production app image собран из `Dockerfile`; изолированный Compose-проект
успешно выполнил migrate и поднял API. После `restart postgres api` сохранились Alembic head,
vector 0.8.1 и тестовый файл в named FileStore volume, readiness вернул ожидаемый `degraded`
при намеренно отсутствующем inference. Smoke-проект и его volumes после проверки удалены.
Затем полный Compose smoke поднял API, inbox, scheduler, outbox, maintenance и Caddy;
после общего restart процессы остались активны, migrate повторно завершился с кодом 0,
а `https://localhost/health/ready` через Caddy вернул ожидаемый `degraded`. В `docker ps`
порты имел только Caddy, не API или PostgreSQL. Smoke-проект и volumes удалены. Это не
проверяет публичный DNS/TLS, live MAX/LLM и обработку общего событийного G3 сценария.

После слияния production Z-модулей smoke повторён на head `0a7b6c5d4e3f`: все 242 теста,
единая миграция/check и двойной seed прошли на PostgreSQL 17.8 + pgvector 0.8.1.
Полный Compose с новым `documents` process пережил общий restart без циклических ошибок.
Backup восстановил новый Z head, vector, 40 public tables и пять файлов с теми же SHA-256;
временные БД, контейнеры и volumes удалены.
GitHub Actions run [#26](https://github.com/hse-shapki/dom-domich/actions/runs/36334824300)
на `c51ec86` затем успешно повторил workflow с целевым PG17/pgvector.
После подключения ordinary problem runtime run
[#31](https://github.com/hse-shapki/dom-domich/actions/runs/36337214973) на `6c11ce9`
успешно выполнил тот же workflow уже с 247 тестами.
После обновления workflow и закрепления `actions/checkout` и `setup-uv` по SHA актуальных
релизов run [#50](https://github.com/hse-shapki/dom-domich/actions/runs/36716287223) на
`2c6af2b` успешно выполнил целевой PG17/pgvector workflow с 275 тестами.

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
