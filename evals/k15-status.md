# K15: итоговая оценка агента

Проверено 30.09.2026. Набор: `evals/k01_cases.jsonl`, 24 синтетических
сообщения. `scripts/evaluate_agent.py` принимает JSONL traces от доверенного
harness и выдаёт отдельно точность маршрутов, recall аварий, покрытие действий,
нарушения запретов, применимость источников, критические кейсы, p50/p95 и
число вызовов tools. Пропуск кейса считается провалом; критические ошибки
перечисляются по ID. Локальные unit-тесты оценщика проходят. В Z-MVP-3
исправлено правило четырёх условий `_or_`: засчитывается фактическая
альтернатива из audit, буквальная строка условия не засчитывается.

`scripts/run_triage_evals.py` воспроизводимо запускает все сообщения через
Ollama и production `LlmTriagePort`. Он фиксирует только валидированные routes,
latency и ошибки schema/transport; `actions` намеренно остаются пустыми, потому
что route-only прогон не исполняет backend tools. Такой trace пригоден для
route accuracy, emergency recall, schema validity и latency, но не закрывает
action/source/access метрики полного K15.

Для route-only прогона на общем стенде A-MVP-1 выбран `qwen3:4b` с digest
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
Prompt классификатора: Git blob `98666c52d3631ca0fa2122318564cca035c8ee21`
файла `src/dom_domych/agent/triage.py`. Demo policy revisions:
`demo-problem-v1`, `demo-initiative-v1`, `demo-resolution-v1`; код policy:
Git blob `49ab93b12624479750daaa7b3136356837ce1a01`.
Это зафиксированная конфигурация, **не результаты оценки**. На текущем хосте
нет работающего Ollama и доступа к общему стенду, поэтому фактические traces
этой модели пока не собраны.

```sh
uv run python scripts/evaluate_agent.py trace.jsonl \
  --model-revision REVISION --prompt-revision REVISION --hardware HOST
```

Формат строки trace: `id`, `routes`, `actions`, `violations`, `source_checks`
(`source_ref`, `reviewed`, `applicable`), `latency_ms`, `tool_calls`. Поля
`actions`, `violations` и `source_checks` собирает harness из фактических
backend events/audit, а не из самоописания модели. Коды действий соответствуют
`required_actions`/`forbidden_actions` dataset. Для ответа по источнику,
заявления о сроке/ответственном и подготовки обращения отсутствие
проверенного source считается ошибкой. Percentiles используют nearest rank.

| Показатель | Реальная модель |
|---|---|
| Exact routes, mixed routes, emergency recall | Не измерены |
| Required/forbidden actions, source validity | Не измерены |
| False merge, access/vote/false registration/close | Не измерены |
| Schema validity, p50/p95, tool calls | Не измерены |

Предыдущий probe на macOS arm64 с 8 GiB RAM: кандидат
`Qwen3-8B-Q4_K_M.gguf` не дал успешного ответа: полный Metal offload упал по
памяти, CPU-only превысил 120 с, частичный offload вызвал swap и зависание.
Ревизии и SHA файлов, лицензии и результаты probe перечислены в
`docs/engineering/11-track-k-inference-probe.md`. GGUF удалены; повторный
запуск этого GGUF на том Mac исключён. Позже A-MVP-1 выбрал и проверил ответ
Ollama `qwen3:4b` на общем стенде; K01/K15 metrics на нём не получены.
G3 model quality остаётся открытым до записи фактических traces. Нулевой
арифметический baseline указан в `evals/README.md`; он не является оценкой модели.
