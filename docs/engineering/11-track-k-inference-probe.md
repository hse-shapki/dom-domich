# K02: состояние проверки inference

Проверено локально 25.09.2026 в рабочей среде ветки `kae`:

- macOS arm64, физическая память 8 GiB (`sysctl hw.memsize`).
- `llama-server` и `llama-cli` не доступны в `PATH`; `.gguf` в домашнем
  каталоге до глубины 4 не найден. Найден исполняемый Docker shim
  `/Users/rol/.docker/bin/inference/llama-server`, но версия и работающий
  inference endpoint не подтверждены. Он не является доказательством
  установленного llama.cpp и весов.
- Model revision, SHA-256 файла, quantization реально загруженного файла,
  память процесса, template/tool calling, русский и p50/p95 **не измерены**.
  Live probe G0 остаётся открытым.

Кандидаты спецификации — [Qwen3-8B-GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF)
`Q4_K_M` и [Qwen3-Embedding-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF).
На карточке текстовой модели указана Apache-2.0 и вариант `Q4_K_M`;
конкретный commit и файл для проекта не выбран. Правила tool calling
сверяются с [документацией llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
перед подключением адаптера. Выбор модели пока не утверждён.

`src/dom_domych/agent/llm.py` содержит `LlmPort`, `FakeLlmPort` и
`RetryingLlmPort`. Обёртка ограничивает время попытки и число повторов
временных ошибок; ошибки валидации не повторяет. HTTPX adapter, конфигурация
endpoint и live benchmark добавляются после A00/A01 и доступного inference
host. Fake путь даёт воспроизводимые unit tests без внешнего вызова.
