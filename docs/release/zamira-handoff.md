# Передача пула Замиры: опросы, инициативы, PDF и результат

Дата исходного handoff: 25.09.2026. Документ описывает состояние пула Z на ту дату.
На 26.09.2026 общий Python-проект, A PostgreSQL-слой и часть K-модулей уже есть;
production Z repositories и рабочий сценарий MAX всё ещё отсутствуют.
Точная готовность каждого блока — в [`context/current-state.md`](../../context/current-state.md).

## Что можно воспроизвести сейчас

Рабочие части Z01–Z13 покрыты unit/fake tests. Ниже сохранены исходные команды
handoff; актуальный проект уже содержит `pyproject.toml` и `uv.lock`, поэтому
общий прогон выполняется через `uv run pytest -q`, `uv run ruff check` и `uv run mypy`.

```bash
PYTHONPATH=src:. uv run --no-project --with reportlab --with pypdf --with pytest --with pytest-asyncio pytest -q -p no:cacheprovider
uvx ruff check src tests scripts
uvx ruff format --check src tests scripts
MYPYPATH=src:. uv run --no-project --with mypy --with reportlab --with types-reportlab --with pypdf --with pytest --with pytest-asyncio mypy --namespace-packages --explicit-package-bases src tests scripts
```

Положительный результат проверки исполнения без ручного изменения БД показывает `test_positive_resident_result_closes_case_and_cancels_future_jobs`, отрицательный — `test_negative_answers_take_priority_and_reopen_case`, нехватку ответов — `test_low_response_does_not_count_as_success` в `tests/domain/test_resolution_service.py`. Эти тесты используют atomic fake и **не доказывают** PostgreSQL-конкуренцию или MAX-доставку.

## Демо-правила и данные

| Версия | Техническое правило | Статус |
|---|---|---|
| `demo-problem-v1` | Пример 20% подтверждений от eligible, ожидание до 5 часов | Не нормативная норма |
| `demo-initiative-v1` | Участие ≥ 50% eligible, поддержка ≥ 60% ответивших | Не кворум ОСС |
| `demo-resolution-v1` | Сначала строго более 20% «нет» среди ответивших → возврат; иначе участие ≥ 50% и «да» ≥ 80% ответивших → закрытие | Политика для демо, требует согласования |
| `demo-reminder-v1` | До двух напоминаний не чаще одного раза в 30 минут, стоп за 5 минут до срока | Временные параметры показа |
| FileStore demo retention | 30 дней, затем отдельная cleanup job | Не утверждённая политика персональных данных |

Синтетический дом и крайние случаи — `tests/fixtures/zamira_house.py`: 12 подходящих жителей одного этажа, несколько подъездов/стояков/домов, недоступная личка, повторяющиеся сообщения, неподходящие аккаунты. Тестовый реестр не является проверкой фактического проживания.

Четыре [образца PDF](../../output/pdf/README.md) воспроизводятся без реальных данных:

```bash
PYTHONPATH=src:. uv run --no-project --with reportlab python scripts/generate_zamira_demo_pdfs.py --output-dir /tmp/dom-domich-pdf-demo
```

Скрипт использует фиксированные факты и даёт тот же текст/число страниц и hash входного snapshot; байтовый hash PDF может меняться из-за метаданных ReportLab. Записанные образцы и визуальная проверка перечислены в [Z15 QA](zamira-pdf-qa.md). В PDF встроены DejaVu Sans и DejaVu Sans Bold; [лицензия DejaVu](../../src/dom_domych/assets/fonts/LICENSE-DejaVu.txt) приложена, а [ReportLab Toolkit](https://docs.reportlab.com/developerfaqs/) используется в открытой редакции. Версии библиотек будут закреплены A00 lockfile.

## Реальные и моделируемые части

| Часть | Сейчас |
|---|---|
| Доменные правила, версии, подсчёт и формирование PDF | Реальный код, проверенный локально |
| Реестр жителей, CasePort, callback/DeliveryPort, outbox/jobs, SQL UoW | Fake/контракт; production-интеграция ещё не сделана |
| Исполнитель, регистрационный номер `DEMO-*`, статусы | Только смоделированный DemoExecutor, без УК/ГИС ЖКХ |
| Официальная отправка/юридический протокол ОСС | Не реализованы; образцы являются подготовленными демо-документами |
| Проверка mobile/web MAX | Не проводилась; строки остаются открытыми в матрице [08](../engineering/08-verification-and-release.md) |

## Что нужно подключить на G1–G3

1. После A00/A01 согласовать типы `TrustedContext`, IDs/UTC/version и порты из [Z00](../engineering/09-z-interfaces.md); обновить фейки и contract tests вместе с реализациями. A предоставляет реестр с явным стояком, actor callback, доставку/jobs, token revocation, FileStore attachment и общий Unit of Work. K предоставляет case/request facts, авторство, исходную аудиторию, версии и безопасные переходы дела.
2. Создать PostgreSQL-модели/миграции Z для audiences, polls/answers/history, initiatives, documents, executor operations и resolution checks. Уникальные ограничения: житель на poll, operation/event key, одна регистрация на request, одна финализация check; все запросы фильтруются по `house_id`. Атомарно сохранять state + outbox/job; не держать SQL lock во время PDF/HTTP/LLM.
3. В G1 проверить настоящий MAX callback (actor, дом, stale revision) и конкуренцию ответов на PostgreSQL. В G2 отправить карточки и PDF через A DeliveryPort, проверить ограниченный доступ к реестру и скачивание в mobile/web. В G3 соединить K RequestService → DemoExecutor → `done` → опрос исходной категории → closed/reopened/unconfirmed с crash/retry. Только после этих прогонов закрывать Z14–Z16.

При сдаче фиксировать commit, versions policy/template/font/model, результаты MAX mobile/web и перечень моделируемых систем. Сейчас такие результаты не заявляются.
