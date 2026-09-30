"""K15: run the K01 routing dataset through a real LlmTriagePort."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from time import perf_counter

import httpx

from dom_domych.agent.triage import LlmTriagePort
from dom_domych.infrastructure.llm.ollama import OllamaPort
from scripts.evaluate_agent import EvalTrace, load_cases


async def run(
    dataset: Path,
    output: Path,
    url: str,
    model: str,
    timeout: float,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    cases = load_cases(dataset)
    traces: list[EvalTrace] = []
    async with httpx.AsyncClient(base_url=url, timeout=timeout, transport=transport) as client:
        triage = LlmTriagePort(OllamaPort(client, model, max_tokens=512))
        for case in cases:
            started = perf_counter()
            routes: tuple[str, ...] = ()
            violations: tuple[str, ...] = ()
            try:
                decision = await triage.classify(case.text)
                routes = tuple(item.kind.value for item in decision.items)
            except (ConnectionError, TimeoutError, ValueError, httpx.HTTPError) as exc:
                violations = (f"triage_error:{type(exc).__name__}",)
            traces.append(
                EvalTrace(
                    id=case.id,
                    routes=routes,
                    actions=(),
                    violations=violations,
                    latency_ms=(perf_counter() - started) * 1000,
                    tool_calls=0,
                )
            )
    output.write_text("".join(trace.model_dump_json() + "\n" for trace in traces), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run route-only K01 evals through Ollama")
    parser.add_argument("--dataset", type=Path, default=Path("evals/k01_cases.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    asyncio.run(run(args.dataset, args.output, args.url, args.model, args.timeout))


if __name__ == "__main__":
    main()
