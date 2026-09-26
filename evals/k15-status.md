# K15: итоговая оценка агента

Проверено 26.09.2026. Набор: `evals/k01_cases.jsonl`, 24 синтетических
сообщения. `scripts/evaluate_agent.py` принимает JSONL traces от доверенного
harness и выдаёт отдельно точность маршрутов, recall аварий, покрытие действий,
нарушения запретов, применимость источников, критические кейсы, p50/p95 и
число вызовов tools. Пропуск кейса считается провалом; критические ошибки
перечисляются по ID. Локальные unit-тесты оценщика проходят.

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

Причина: на доступном macOS arm64 с 8 GiB RAM кандидат
`Qwen3-8B-Q4_K_M.gguf` не дал успешного ответа: полный Metal offload упал по
памяти, CPU-only превысил 120 с, частичный offload вызвал swap и зависание.
Ревизии и SHA файлов, лицензии и результаты probe перечислены в
`docs/engineering/11-track-k-inference-probe.md`. GGUF удалены; повторный
запуск на этом Mac исключён. Текстовый кандидат и embedding кандидат **не
утверждены**. Prompt revision для реальной модели не выбран. G0/G3 model
quality остаются открытыми до запуска на отдельном подходящем хосте и записи
фактических traces. Нулевой арифметический baseline указан в `evals/README.md`;
он не является оценкой модели.
