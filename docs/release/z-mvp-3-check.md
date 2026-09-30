# Z-MVP-3: проверка результата и agent evals

Статус 30.09.2026: локальная проверка пройдена; цельный MAX/LLM G3 на общем
стенде ещё не пройден. Этот порядок рассчитан на `demo=true` дом и синтетических
подтверждённых взрослых жителей. Записывайте commit backend, UTC, версии MAX
mobile/web, model digest и policy revisions. Токены, личные сообщения и данные
квартир в evidence не сохраняйте.

## До сообщений в MAX

1. На общем стенде проверьте `docker compose -f deploy/compose.yml ps` и
   `uv run python -m scripts.max_operations probe`. Убедитесь, что работают
   polling, inbox, scheduler, outbox, documents, PostgreSQL и Ollama; probe
   должен подтвердить MAX `/me`, отсутствие webhook и ответ выбранной модели.
2. Через demo onboarding привяжите синтетических жителей и домовой чат.
   Подготовьте проверенный scoped источник правила и ответственного; иначе
   агент должен уточнять, а обращение нельзя отправлять. Для каждого типа
   дела используйте новую формулировку и локацию.
3. Сохраните model digest, Git blob prompt и revisions demo policies из
   [K15 status](../../evals/k15-status.md). Не записывайте метрики модели,
   пока не собраны реальные traces.

## Дело → demo executor → исход

1. По отдельности заведите в MAX обычную проблему, инициативу и аварию.
   Пройдите их естественный путь до явно согласованного demo-обращения;
   подробные команды жителя и пороги — в [сценарии](zamira-manual-demo.md).
   Авария не ждёт начального poll; инициатива проходит новую редакцию и
   решение позиции. В группе видны только агрегаты, PDF приходит лично.
2. Оператор на стенде запускает `list` для UUID demo-дома и находит
   `operation_id` нужного обращения. Выполняет `register`, затем ту же
   команду повторно. Первый ответ: `status=registered`, `registration=DEMO-*`,
   `emitted=True`; второй: `emitted=False`. Проверьте личный PDF обращения
   и отсутствие его в группе.
3. Оператор создаёт один UUID события и выполняет `done --event-id UUID`,
   затем повторяет **тот же UUID**. Первый ответ содержит `status=done`
   и `emitted=True`, второй — `emitted=False`. Дело должно перейти в
   `checking_resolution`, оставаясь открытым. Начальный состав адресатов
   не меняется от недоставленной лички или новых жильцов.
4. Проведите три отдельных опроса результата по `demo-resolution-v1`:
   все 12 исходных жителей отвечают «да» → `closed`; три из 12 отвечают
   «нет», остальные «да» → `reopened`; никто не отвечает →
   `resolution_unconfirmed`. Финализация происходит после двух часов,
   поэтому используйте заранее начатые дела, не меняя часы/статусы в БД.
   Отрицательный итог не теряет историю дела и создаёт продолжение.
5. Повторите `done` после финализации; исход и версия дела не должны меняться.
   Для аварии убедитесь, что опрос создан без начального poll. Для инициативы
   убедитесь, что использована действующая редакция, но исходная аудитория.

Команды оператора (UUID подставляются только из demo-стенда):

```bash
docker compose -f deploy/compose.yml exec api python -m dom_domych.entrypoints.zamira_operator list --house-id HOUSE_UUID
docker compose -f deploy/compose.yml exec api python -m dom_domych.entrypoints.zamira_operator register --house-id HOUSE_UUID --operation-id OPERATION_UUID
docker compose -f deploy/compose.yml exec api python -m dom_domych.entrypoints.zamira_operator done --house-id HOUSE_UUID --operation-id OPERATION_UUID --event-id EVENT_UUID
```

## Дедлайн и восстановление

1. Для зарегистрированного demo-обращения с проверенным правилом дождитесь
   применимого deadline. Ожидается только review-only followup и личный PDF
   черновика жалобы уполномоченному жителю; автоматической официальной
   отправки нет. Повтор due job не создаёт второй черновик, старый job после
   закрытия дела пропускается. Срок без проверенного origin не утверждайте.
2. После `done` временно остановите один worker и восстановите его штатным
   Compose restart. Проверьте, что pending событие доходит один раз, а
   повтор operator команды не создаёт новый опрос. Остановите личку одного
   синтетического жителя: недоставка видна в delivery state, но не уменьшает
   frozen denominator. Зафиксируйте фактический outbox статус.
3. Отметьте результаты по двум клиентам только в
   [матрице MAX](max-mobile-web-matrix.md): callback, изменение статуса,
   подтверждение/отклонение выполнения, недоставка и открытие PDF. Каждой
   строке нужны дата, версия клиента, commit и обезличенное evidence.

Локальная опора без живого MAX: `tests/infrastructure/test_g3_runtime.py`
проводит 9 комбинаций через operator CLI, durable inbox, PDF/FileStore и
PostgreSQL. `test_z12_resolution_postgres.py` проверяет исходную аудиторию,
поздний replay и stale jobs; `test_k14_deadline_cycle.py` и
`test_z08_followup_postgres.py` проверяют deadline и приватный черновик.

## K01/K15 на выбранной модели

На стенде с работающим Ollama запустите 24 независимых сообщения через
production классификатор. `--url` задаётся адресом доступного Ollama на
стенде, не адресом MAX. Сохраните JSONL, commit, digest модели, prompt blob,
hardware и время. В routes JSONL нет вызовов backend tools, поэтому из
этого прогона сообщайте только route accuracy, emergency recall, ошибки
schema/transport и latency. Остальные метрики требуют harness с фактическим
tool/case/source audit; отдельно перечислите все восемь critical cases.

```bash
uv run python scripts/run_triage_evals.py --model qwen3:4b --url http://127.0.0.1:11434 --output /tmp/k01-routes.jsonl
uv run python scripts/evaluate_agent.py /tmp/k01-routes.jsonl --model-revision MODEL_DIGEST --prompt-revision PROMPT_BLOB --hardware HOST
```

Числа из route-only вывода не называйте полной K15 оценкой: поля
`required_covered` и `critical_failure_ids` в таком trace учитывают пустые
`actions`. В полноценном прогоне добавьте валидированные вызовы и факты
источников, запреты и отдельное расследование каждого critical failure.
