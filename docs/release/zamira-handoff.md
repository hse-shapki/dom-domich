# Передача пула Замиры: опросы, инициативы, PDF и результат

Обновлено 30.09.2026 на ветке `z-live-feedback`. Точный статус всех модулей — в
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
Публикация карточки, выпуск кнопок, callback с доверенным actor, приватное
подтверждение и автоматический edit — в
[`test_z05_poll_callback_postgres.py`](../../tests/infrastructure/test_z05_poll_callback_postgres.py)
и [`test_z07_cards_outbox.py`](../../tests/infrastructure/test_z07_cards_outbox.py).
Четыре PDF через worker/FileStore/MAX MockTransport — в
[`test_z10_max_pdf_pipeline.py`](../../tests/infrastructure/test_z10_max_pdf_pipeline.py);
lease/recovery — в [`test_z09_documents_postgres.py`](../../tests/infrastructure/test_z09_documents_postgres.py).
Единый problem → callback/card → request/PDF → demo executor → closed/reopened — в
[`test_g3_runtime.py`](../../tests/infrastructure/test_g3_runtime.py).
Эти тесты позволяют воспроизвести обе развилки результата без изменения БД вручную.

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
| PostgreSQL аудитории, опросы, инициативы, документы, demo executor и проверка результата | Реализованы частично; локальные PostgreSQL concurrency/idempotency и G3-пути проверены; актуальное число полного набора — в `context/current-state.md` |
| MAX callback, outbox, кнопки, PDF upload | Подключены к process root; callback голос/личный ответ/edit и четыре PDF upload проверены PostgreSQL/MockTransport. Ранее live callback вне аудитории отклонён; допустимый live голос/edit/PDF не проверены |
| Исполнитель и `DEMO-*` регистрация | Только смоделированный DemoExecutor, без УК/ГИС ЖКХ; операторская capability обязательна |
| Дело и агент | Ordinary problem → audience/poll/card и K request связаны локально; полный live MAX/LLM G3 и инициативный маршрут с моделью требуют отдельной проверки |
| Официальная отправка и протокол ОСС | Не реализованы; четыре PDF являются демо-документами, протокол назван позицией жителей |
| MAX mobile/web, публичный HTTPS и цельный live inference/G3 | Не проверены; прежний live callback вне frozen audience и доставка групповой карточки отмечены отдельно в `context/current-state.md` |

## Точный ручной сценарий и оставшиеся проверки

Пошаговый сценарий двух дел с порогами `3/12`, позитивным `12/12`, негативным
`3/12` и безопасными командами operator CLI — в
[`zamira-manual-demo.md`](zamira-manual-demo.md). CLI
[`zamira_operator.py`](../../src/dom_domych/entrypoints/zamira_operator.py)
допускает только `demo=true` дом, повтор `register` и `done` с тем же event ID не
создаёт второго события. Проверка четырёх файлов в MAX описана отдельно в
[`zamira-live-pdf-smoke.md`](zamira-live-pdf-smoke.md).

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
5. На G2/G3 проверить весь путь в живом MAX mobile/web: допустимый callback и
   видимое ЛС, edit карточки, открытие четырёх PDF, недоставку и восстановление.
   Для полного цикла нужна проверенная live модель, reviewed правило, два часа
   ожидания финализации result poll и фактические screenshots; локальный G3 не
   закрывает Z14–Z16 или release gate.

Для сдачи фиксируют commit, версии policy/template/font/model, результаты MAX
mobile/web и список моделируемых систем. Live результаты сейчас не заявляются.
