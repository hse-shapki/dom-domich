# Проверенное состояние проекта

Проверено 25.09.2026 по рабочему дереву репозитория. Этот файл меняется после реализации задач; старое значение статуса не является вечной истиной.

## Факты на дату проверки

| Область | Состояние | Проверяемое основание |
|---|---|---|
| Продуктовая концепция и журнал решений | Есть документация | `IDEA.md`, `docs/backlog.md`, `docs/open-questions.md` |
| Техническая архитектура, ограничения, треки и приёмка | Есть проектная документация | `docs/engineering/README.md` и восемь документов в той же папке |
| Персональные пулы технических задач | Спланированы, часть Z-пула реализована | `context/implementation-plan.md`, `tasks-alina.md`, `tasks-katerina.md`, `tasks-zamira.md` |
| Корневые правила для агентов | Есть | `AGENTS.md` |
| Постоянный контекст | Есть | `context/README.md`, `decisions.md`, `product.md`, `engineering.md`, `current-state.md` |
| Чистые доменные правила опросов Z01 | Проверены на unit-уровне | `src/dom_domych/domain/polls/policy.py`, `tests/domain/test_poll_policy.py`: 23 теста |
| Предложение контрактов Z00 | Частично: описано, не согласовано на A01 | `docs/engineering/09-z-interfaces.md`; общих DTO и contract tests пока нет |
| Синтетический дом Z02 | Проверен как fixture, не интегрирован с A02 | `tests/fixtures/zamira_house.py`, `tests/fixtures/test_zamira_house.py`: 4 теста |
| AudienceService Z03 | Частично: выбор и история snapshot проверены на fake | `src/dom_domych/domain/audiences/models.py`, `src/dom_domych/application/audiences/service.py`, `tests/domain/test_audience_service.py`; нет PostgreSQL repository/migration |
| PollService Z04 | Частично: поведение и конкуренция проверены на fake | `src/dom_domych/domain/polls/models.py`, `src/dom_domych/application/polls/service.py`, `tests/domain/test_poll_service.py`; нет PostgreSQL repository/migration и MAX callback |
| Callback handler Z05 | Частично: token/actor/revision/expiry проверены на fake | `src/dom_domych/application/polls/callback.py`, `tests/domain/test_poll_callback.py`; нет A10 MAX transport/action storage |
| InitiativeService Z06 | Частично: редакции и замена poll проверены на fake | `src/dom_domych/domain/initiatives/models.py`, `src/dom_domych/application/initiatives/service.py`, `tests/fakes/initiatives.py`, `tests/domain/test_initiative_service.py`; нет K CasePort, PostgreSQL UoW и MAX token revocation |
| Публичные карточки Z07 | Частично: тексты/шкалы проверены unit-тестами | `src/dom_domych/application/cards/builders.py`, `tests/domain/test_public_cards.py`; нет A DeliveryPort/edit/coalescing |
| Напоминания и итог инициативы Z08 | Частично: частотный лимит и supported/not_supported проверены на fake | `src/dom_domych/application/initiatives/followup.py`, `tests/fakes/initiative_followup.py`, `tests/domain/test_initiative_followup.py`; нет A DeliveryPort/jobs и K RequestService |
| FileStore и immutable snapshot Z09 | Частично: проверены локально | `src/dom_domych/infrastructure/files/local.py`, `src/dom_domych/domain/documents/snapshot.py`, тесты в `tests/infrastructure/` и `tests/domain/test_document_snapshot.py`; нет PDF worker и PostgreSQL metadata |
| PDF-рендер Z10 | Частично: 4 шаблона проверены локально | `src/dom_domych/infrastructure/documents/renderer.py`, `tests/infrastructure/test_pdf_renderer.py`, 4 синтетических образца в `output/pdf/`; нет durable PDF job/outbox и MAX download |
| DemoExecutor Z11 | Частично: команда и переходы проверены на fake | `src/dom_domych/domain/executor/models.py`, `src/dom_domych/application/executor/service.py`, `tests/fakes/executor.py`, `tests/domain/test_demo_executor.py`; нет PostgreSQL repository/outbox и связи с K RequestService |
| Старт проверки результата Z12 | Частично: done → исходная аудитория/poll проверены на fake | `src/dom_domych/domain/resolution/models.py`, `src/dom_domych/application/resolution/service.py`, `tests/fakes/resolution.py`, `tests/domain/test_resolution_service.py`; нет K CasePort, PostgreSQL UoW и MAX-доставки |
| Итоги проверки результата Z13 | Частично: closed/reopened/unconfirmed проверены на fake | Те же файлы resolution; отдельный K production transition и отмена jobs ещё нужны |
| PDF QA Z15 | Частично: локально просмотрены 4 образца | `docs/release/zamira-pdf-qa.md`; mobile/web MAX и outbox ещё не проверены |
| Материалы Z16 | Частично: локальный handoff и воспроизведение PDF готовы | `docs/release/zamira-handoff.md`, `scripts/generate_zamira_demo_pdfs.py`; сквозной runbook ждёт A/K интеграции |
| Python-проект и зависимости | Не реализованы | Есть независимый Z-модуль в `src/`, но нет `pyproject.toml`, `uv.lock` и общего пакета A00 |
| БД, миграции, MAX-клиент, агент, хранение опросов | Не обнаружены | Нет кода интеграций и `migrations/` |
| Рабочий стенд и внешние проверки | Не подтверждены | Нет `deploy/`; доступ MAX/модели в этом проекте не проверялся |

Эти строки описывают только осмотр репозитория. Они не доказывают отсутствие внешнего аккаунта или бота у команды. И наоборот, схема в Markdown не доказывает готовность реализации.

## Следующий шаг по утверждённому плану

Продолжить G0 из [плана трёх пулов](implementation-plan.md): Алина делает A00 (Python-каркас), Катерина и Замира — K00/Z00 (предложения стыков), затем A01 закрепляет contracts. Предложение Z00 и fixture Z02 готовы для согласования; Z01 и Z07 проверены на unit-уровне, Z03–Z06, Z08 и Z11–Z13 — на fakes, Z09–Z10 — локально. Дальше необходима интеграция Z с A/K: общий контракт A01/K00, PostgreSQL migrations/UoW, MAX callbacks/delivery и сквозные проверки Z14–Z16. Доступ MAX/LLM и готовность стенда проверяются отдельно.

## Как обновлять после задачи

1. Сверить `git status`, файлы и результаты подходящих проверок.
2. Обновить только затронутые строки, указав пути к реализации и точную степень проверки: «частично», «реализовано, не проверено» или «проверено».
3. Синхронизировать раздел «Что уже сделано» в [AGENTS.md](../AGENTS.md) и при необходимости вводную страницу [инженерных документов](../docs/engineering/README.md).
4. Сохранить важный новый выбор в [решениях](decisions.md), а подробности — в соответствующей инженерной спецификации.
5. Включить изменения контекста в коммит выполненной задачи.

Не записывать сюда токены, настоящие данные жильцов или непроверенное утверждение «работает в MAX».
