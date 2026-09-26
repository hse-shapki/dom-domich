"""Воспроизводимый локальный probe русского chat/tool calling без секретных данных."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from statistics import median
from time import perf_counter

import httpx

from dom_domych.infrastructure.llm.llama_server import LlamaServerPort


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


async def probe(url: str, model: str, samples: int) -> dict[str, object]:
    timings: list[float] = []
    calls: list[dict[str, object]] = []
    schema: list[dict[str, object]] = [
        {
            "name": "case.search",
            "description": "Ищет похожие дела в текущем доме",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    prompts = (
        "На лестнице третьего подъезда не горит лампа. Найди похожие дела.",
        "Сильно пахнет газом в подъезде. Что нужно сделать срочно?",
        "Кто отвечает за освещение общего коридора, если источник не найден?",
    )
    async with httpx.AsyncClient(base_url=url, timeout=120.0) as client:
        port = LlamaServerPort(client, model, max_tokens=128)
        for index in range(samples):
            prompt = prompts[index % len(prompts)]
            started = perf_counter()
            response = await port.complete(
                [
                    {
                        "role": "system",
                        "content": "Отвечай по-русски. Не выдумывай норму или регистрацию.",
                    },
                    {"role": "user", "content": prompt},
                ],
                schema if index % len(prompts) == 0 else [],
            )
            timings.append(perf_counter() - started)
            calls.append(
                {
                    "scenario": index % len(prompts),
                    "text_present": bool(response.text.strip()),
                    "tool_names": [call.name for call in response.tool_calls],
                    "valid_tool_json": all(
                        _valid_json(call.arguments_json) for call in response.tool_calls
                    ),
                }
            )
    return {
        "samples": samples,
        "p50_seconds": round(median(timings), 3),
        "p95_seconds": round(_percentile(timings, 0.95), 3),
        "results": calls,
    }


def _valid_json(raw: str) -> bool:
    try:
        return isinstance(json.loads(raw), dict)
    except json.JSONDecodeError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный K02 inference probe")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", required=True)
    parser.add_argument("--samples", type=int, default=6)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples должен быть положительным")
    print(json.dumps(asyncio.run(probe(args.url, args.model, args.samples)), ensure_ascii=False))


if __name__ == "__main__":
    main()
