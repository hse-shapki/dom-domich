# Передача пула Замиры: опросы, инициативы, PDF и результат

Обновлено 30.09.2026 после объединения Z изменений с MAX/callback/Ollama изменениями `origin/main`. Точный статус всех модулей — в
[`context/current-state.md`](../../context/current-state.md). Положительные локальные
тесты не заменяют приёмку в живом MAX.

## Локальное воспроизведение

Нужны `uv`, PostgreSQL и пустая отдельная БД с именем, содержащим `test`.
Команды из корня репозитория (имя БД и URL адаптировать к своему локальному серверу):

```bash
createdb dom_domych_test_zamira
DATABASE_URL=postgresql+asyncpg://localhost/dom_domych_test_zamira uv run alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://localhost/dom_domych_test_zamira uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
DATABASE_URL=postgresql+asyncpg://localhost/dom_domych_test_zamira uv run alembic check
```

Тесты Z03–Z14 создают только синтетические дела/жильцов. Повторный запуск
отдельных тестов на уже использованной БД может столкнуться с данными других
тестов outbox; для общего прогона берут чистую БД. Положительный, отрицательный
и неподтверждённый исходы проверяются параметризованным
[`test_z12_resolution_postgres.py`](../../tests/infrastructure/test_z12_resolution_postgres.py).
Регистрация, повтор и запрет жителю менять статус исполнителя — в
[`test_z11_demo_executor_postgres.py`](../../tests/infrastructure/test_z11_demo_executor_postgres.py).
Публикация карточки, выпуск кнопок, callback с доверенным actor и обновление
карточки — в [`test_z07_cards_outbox.py`](../../tests/infrastructure/test_z07_cards_outbox.py).
Загрузка PDF после durable job в FileStore и приватный outbox — в
[`test_z09_documents_postgres.py`](../../tests/infrastructure/test_z09_documents_postgres.py).
Эти тесты позволяют воспроизвести все три исхода результата без изменения БД вручную.
Дополнительно `test_g3_runtime_callback.py` проверяет problem → MAX callback/card
→ request/PDF → demo executor → closed/reopened, а `test_z10_max_pdf_pipeline.py`
проводит четыре PDF через PostgreSQL/FileStore/MAX MockTransport.

## Ручной demo executor и приватный реестр

Оператор запускает команды локально на стенде с `DATABASE_URL` в окружении.
Доступ к процессу и БД является границей служебных полномочий; команды не
публикуются как tools для LLM или команды жильца. CLI отклоняет дом без `demo=true`.
Обращение уже должно быть согласовано жителем и submitted через RequestService.

```bash
uv run python -m dom_domych.entrypoints.zamira_operator show --house-id HOUSE_UUID --request-id REQUEST_UUID
uv run python -m dom_domych.entrypoints.zamira_operator register --house-id HOUSE_UUID --request-id REQUEST_UUID
uv run python -m dom_domych.entrypoints.zamira_operator status --house-id HOUSE_UUID --request-id REQUEST_UUID --status done --event-id EVENT_UUID
```

Вместо `*_UUID` берут идентификаторы синтетического дома/обращения, а `EVENT_UUID`
выбирают один раз и сохраняют для повторов команды. Ответ содержит demo registration,
external status и признак нового события. Повтор не создаёт вторую регистрацию или
событие. Inbox затем запускает личный опрос результата; CLI `done` сам дело не закрывает.
Жители отвечают через свои кнопки: достаточно «да» → `closed`, отрицательный порог →
`reopened`, недостаточно ответов → `resolution_unconfirmed`.

После итогового решения инициативы позиция жителей автоматически идёт автору.
После доверенного deadline K сохраняет review-only текст, а Z ставит PDF черновика
жалобы в очередь для согласовавшего обращение жителя. Это не официальная отправка.

Приватный реестр начальных личных приглашений готовит только оператор для
назначенного уполномоченного подтверждённого жителя:

```bash
uv run python -m dom_domych.entrypoints.zamira_operator document --house-id HOUSE_UUID --case-id CASE_UUID --recipient-id RESIDENT_UUID --kind notification_register --operation-key demo-notice-register-1
```

Operation key сохраняют для повторов: существующий PDF не переснимает изменившиеся
delivery states. Для нового снимка задают новый ключ. Отдельная capability
`document.notice_register` проверяется application service; авторство инициативы
само по себе не даёт права на реестр. Реестр содержит внутренние ID и идёт только
лично. Время попыток отсутствует в outbox и в PDF не выдумывается.

## Проверка локального G3

В `tests/infrastructure/test_g3_runtime.py` параметризованы три вида дела и три
исхода результата: **9 сценариев** с production repositories, durable inbox,
request approval/submit, настоящим PDF worker/FileStore и DemoExecutor.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://localhost/dom_domych_test_zamira uv run pytest tests/infrastructure/test_g3_runtime.py -q
```

Это не live G3: вход в этих тестах — typed case command, голоса записываются
доверенными test actors, MAX transport проверен отдельно MockTransport. Авторская
редакция инициативы обновляет common case text/version и карточку через inbox;
сценарий её запуска пользователем в MAX нужно проверить совместно с K/A.

## Демо-правила и данные

| Версия | Техническое правило | Статус |
|---|---|---|
| `demo-problem-v1` | Пример 20% подтверждений от eligible, ожидание до 5 часов | Не нормативная норма |
| `demo-initiative-v1` | Участие ≥ 50% eligible, поддержка ≥ 60% ответивших | Не кворум ОСС |
| `demo-resolution-v1` | Сначала строго более 20% «нет» среди ответивших → возврат; иначе участие ≥ 50% и «да» ≥ 80% ответивших → закрытие | Демо-политика, требует согласования |
| `demo-reminder-v1` | До двух напоминаний не чаще одного раза в 30 минут, стоп за 5 минут до срока | Временные параметры показа |
| FileStore demo retention | 30 дней, затем cleanup job | Не утверждённая политика персональных данных |

Синтетический дом и крайние случаи —
[`zamira_house.py`](../../tests/fixtures/zamira_house.py): 12 подходящих жителей
одного этажа, несколько подъездов/стояков/домов, недоступная личка,
повторяющиеся сообщения и неподходящие аккаунты. Тестовый реестр не доказывает
фактическое проживание.

Четыре [образца PDF](../../output/pdf/README.md) воспроизводятся без реальных данных:

```bash
uv run python scripts/generate_zamira_demo_pdfs.py --output-dir /tmp/dom-domich-pdf-demo
```

Текст/страницы и hash входного snapshot стабильны; байтовый hash PDF может
меняться из-за метаданных ReportLab. В PDF встроены DejaVu Sans и DejaVu Sans Bold;
[лицензия шрифта](../../src/dom_domych/assets/fonts/LICENSE-DejaVu.txt) приложена,
а ReportLab используется в открытой редакции. Версии зависимостей закреплены в
[`uv.lock`](../../uv.lock). Результаты просмотра — в [Z15 QA](zamira-pdf-qa.md).

## Что реально подключено

| Часть | Состояние |
|---|---|
| PostgreSQL аудитории, опросы, инициативы, документы, demo executor и проверка результата | Частично: 9 G3 комбинаций проверены на PostgreSQL 17.8/pgvector; новый callback/PDF/CLI набор проходил на PG16.13 до объединения; текущий прогон указан в `context/current-state.md` |
| MAX callback, outbox, кнопки, PDF upload | Callback → приватный feedback/edit и четыре PDF через MAX upload проверены PostgreSQL/MockTransport; Z-MVP-2 дополнительно провёл реальные producer-события четырёх PDF до приватной отправки. Live MAX подтвердил доставку групповой карточки, отказ callback вне аудитории и синтетический PDF transport, но допустимый голос, доменный edit и Z файлы в mobile/web открытыми не проверены. Ручной порядок — [Z-MVP-2](z-mvp-2-manual-check.md) |
| Исполнитель и `DEMO-*` регистрация | Только смоделированный DemoExecutor, без УК/ГИС ЖКХ; операторская capability обязательна |
| Дело и агент | K problem/initiative/emergency opening, request approval/submit/PDF binding и результат связаны; 9 локальных production сценариев прошли. Ollama провёл отдельный problem path; цельный live MAX/LLM G3 не проверен |
| Официальная отправка и протокол ОСС | Не реализованы; четыре PDF являются демо-документами, протокол назван позицией жителей |
| MAX mobile/web, публичный HTTPS и цельный live G3 | Частично: отдельные live transport probes есть; полный путь, публичный HTTPS и оба клиента остаются открытыми в [матрице](max-mobile-web-matrix.md) |

## Точный ручной сценарий и оставшиеся проверки

Два дела с порогами `3/12`, позитивным `12/12` и негативным `3/12` описаны в
[`zamira-manual-demo.md`](zamira-manual-demo.md). Все четыре приватных PDF
проверяются по [`zamira-live-pdf-smoke.md`](zamira-live-pdf-smoke.md).
Полный контрольный лист Z-MVP-3 по трём типам дела, трём исходам,
replay/недоставке, deadline и K01/K15 — в
[`z-mvp-3-check.md`](z-mvp-3-check.md). На чистой PG16.13 все девять локальных
G3 сочетаний теперь проходят именно через operator CLI register/done/replay;
live MAX/LLM G3 и реальные метрики модели ещё открыты.
Локальный CLI поддерживает и `--request-id`, и `--operation-id`; команды
`list`/`done` удобны для ручного демо. Повтор с тем же `event-id` не создаёт
второе событие.

1. Подтверждённому жителю назначают проживание и MAX ID через demo onboarding.
   Выбор аудитории фиксирует всех eligible, независимо от доставки личных сообщений.
2. Опрос открывается с версией demo policy; общая карточка несёт только суммарные
   шкалы и непрозрачные кнопки. Нажатие проходит MAX actor → action token →
   PostgreSQL PollRepository. При смене инициативы старый poll и токены отзываются.
3. После согласования черновика K RequestService вызывает DemoExecutor. Доверенная
   регистрация создаёт номер `DEMO-*`; только actor с `demo_executor.operator`
   может поставить `done`. Этот статус запускает личный опрос исходной аудитории
   и оставляет дело открытым до ответа жителей.
4. Достаточная поддержка результата закрывает дело; отрицательный порог возвращает
   его в работу; недостаток ответов оставляет `resolution_unconfirmed`.
   Все три ветки и повтор события проверены PostgreSQL-тестами.
5. На G2/G3 проверить весь путь в живом MAX mobile/web: callback, права на личку,
   открытие четырёх PDF после outbox, поведение при недоставке и восстановление
   после перезапуска. Для live цикла нужны действующий бот/HTTPS и работоспособная модель. Лишь после этого можно закрывать Z14–Z16 и release gate.

Для сдачи фиксируют commit, версии policy/template/font/model, результаты MAX
mobile/web и список моделируемых систем. Live результаты сейчас не заявляются.
