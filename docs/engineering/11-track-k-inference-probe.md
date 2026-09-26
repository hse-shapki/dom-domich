# K02: состояние проверки inference

Проверено локально 26.09.2026 в рабочей среде ветки `kae`:

- macOS arm64, физическая память 8 GiB (`sysctl hw.memsize`).
- Установлен Homebrew `llama.cpp` 0.5.0, build 11146 (`7fe450e19`).
- Во временный cache вне репозитория загружался `Qwen3-8B-Q4_K_M.gguf`, revision
  `7c41481f57cb95916b40956ab2f0b139b296d974`, SHA-256
  `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`,
  размер 5 027 783 488 байт. Карточка модели указывает Apache-2.0.
- Загружался `Qwen3-Embedding-0.6B-Q8_0.gguf`, revision
  `370f27d7550e0def9b39c1f16d3fbaa13aa67728`, SHA-256
  `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`,
  размер 639 150 592 байта; лицензия карточки — Apache-2.0.
- Текстовая модель с полным Metal offload завершилась ошибкой нехватки GPU
  памяти. CPU-only запуск загрузился, но первый запрос превысил timeout 120 с.
  Частичный Metal offload вызвал сильный swap и зависание рабочего Mac; процесс
  остановлен. Успешных ответов нет, поэтому русский, tool calling, p50/p95 и
  рабочая память **не подтверждены**. На этом 8 GiB Mac повторный probe не
  выполняется. После проверки оба GGUF удалены из cache, освобождено около
  5,7 ГБ диска. G0 inference остаётся открытым до проверки на другом хосте.

Кандидаты спецификации — [Qwen3-8B-GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF)
`Q4_K_M` и [Qwen3-Embedding-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF).
На карточке текстовой модели указана Apache-2.0 и вариант `Q4_K_M`;
конкретные файлы и revisions указаны выше. Правила tool calling
сверяются с [документацией llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
перед подключением адаптера. Выбор модели пока не утверждён.

`src/dom_domych/agent/llm.py` содержит `LlmPort`, `FakeLlmPort` и
`RetryingLlmPort`. `infrastructure/llm/llama_server.py` реализует HTTPX
adapter к `/v1/chat/completions`; `scripts/probe_k02.py` сохраняет методику
замера. Обёртка ограничивает время попытки и число повторов временных ошибок;
ошибки валидации не повторяет. HTTPX MockTransport и fake путь дают
воспроизводимые tests без нагрузки на Mac.
