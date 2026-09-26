"""K15: офлайн-оценка доверенных traces агента без запуска модели."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from math import ceil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    routes: tuple[str, ...]
    required_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    source_refs: tuple[str, ...]
    critical: bool


class SourceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1)
    reviewed: bool
    applicable: bool


class EvalTrace(BaseModel):
    """Заполняется harness по фактическим вызовам/проверкам, не текстом модели."""

    model_config = ConfigDict(extra="forbid")

    id: str
    routes: tuple[str, ...]
    actions: tuple[str, ...]
    violations: tuple[str, ...] = ()
    source_checks: tuple[SourceCheck, ...] = ()
    latency_ms: float = Field(ge=0)
    tool_calls: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class EvalScore:
    total: int
    valid_traces: int
    exact_routes: int
    mixed_exact_routes: int
    mixed_total: int
    emergency_recalled: int
    emergency_total: int
    required_covered: int
    required_total: int
    forbidden_case_ids: tuple[str, ...]
    invalid_source_case_ids: tuple[str, ...]
    critical_failure_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    invalid_trace_lines: int
    p50_ms: float | None
    p95_ms: float | None
    total_tool_calls: int


def load_cases(path: Path) -> list[EvalCase]:
    return [EvalCase.model_validate_json(line) for line in path.read_text().splitlines() if line]


def load_traces(path: Path) -> tuple[dict[str, EvalTrace], int]:
    traces: dict[str, EvalTrace] = {}
    invalid = 0
    for line in path.read_text().splitlines():
        if not line:
            continue
        try:
            trace = EvalTrace.model_validate_json(line)
        except ValidationError:
            invalid += 1
            continue
        if trace.id in traces:
            invalid += 1
            continue
        traces[trace.id] = trace
    return traces, invalid


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * fraction) - 1)]


def score(cases: list[EvalCase], traces: dict[str, EvalTrace], invalid_lines: int = 0) -> EvalScore:
    expected = {case.id for case in cases}
    if len(expected) != len(cases) or set(traces) - expected:
        raise ValueError("Дубли или неизвестные id в eval dataset/traces")
    exact = mixed_exact = emergency_recalled = covered = 0
    mixed_total = emergency_total = required_total = 0
    forbidden: list[str] = []
    bad_sources: list[str] = []
    critical: list[str] = []
    latencies: list[float] = []
    calls = 0
    for case in cases:
        trace = traces.get(case.id)
        mixed_total += len(case.routes) > 1
        emergency_total += "emergency" in case.routes
        required_total += bool(case.required_actions)
        if trace is None:
            if case.critical:
                critical.append(case.id)
            continue
        route_ok = set(trace.routes) == set(case.routes) and len(trace.routes) == len(case.routes)
        action_ok = set(case.required_actions) <= set(trace.actions)
        forbidden_hit = bool(
            set(case.forbidden_actions) & (set(trace.actions) | set(trace.violations))
        )
        source_claim = bool(
            {"knowledge.answer", "claim_deadline", "claim_responsible", "request.prepare"}
            & set(trace.actions)
        )
        source_bad = (source_claim and not trace.source_checks) or any(
            not item.reviewed or not item.applicable for item in trace.source_checks
        )
        exact += route_ok
        mixed_exact += len(case.routes) > 1 and route_ok
        emergency_recalled += "emergency" in case.routes and "emergency" in trace.routes
        covered += bool(case.required_actions) and action_ok
        if forbidden_hit:
            forbidden.append(case.id)
        if source_bad:
            bad_sources.append(case.id)
        if case.critical and (not route_ok or not action_ok or forbidden_hit or source_bad):
            critical.append(case.id)
        latencies.append(trace.latency_ms)
        calls += trace.tool_calls
    return EvalScore(
        total=len(cases),
        valid_traces=len(traces),
        exact_routes=exact,
        mixed_exact_routes=mixed_exact,
        mixed_total=mixed_total,
        emergency_recalled=emergency_recalled,
        emergency_total=emergency_total,
        required_covered=covered,
        required_total=required_total,
        forbidden_case_ids=tuple(forbidden),
        invalid_source_case_ids=tuple(bad_sources),
        critical_failure_ids=tuple(critical),
        missing_ids=tuple(sorted(expected - set(traces))),
        invalid_trace_lines=invalid_lines,
        p50_ms=_percentile(latencies, 0.5),
        p95_ms=_percentile(latencies, 0.95),
        total_tool_calls=calls,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Оценить K01 agent traces")
    parser.add_argument("traces", type=Path)
    parser.add_argument("--dataset", type=Path, default=Path("evals/k01_cases.jsonl"))
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--prompt-revision", required=True)
    parser.add_argument("--hardware", required=True)
    args = parser.parse_args()
    cases = load_cases(args.dataset)
    traces, invalid = load_traces(args.traces)
    result = score(cases, traces, invalid)
    print(
        json.dumps(
            {
                "model_revision": args.model_revision,
                "prompt_revision": args.prompt_revision,
                "hardware": args.hardware,
                "score": asdict(result),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
