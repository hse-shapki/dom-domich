"""K15: метрики сохраняют критические провалы отдельно от среднего."""

from pathlib import Path

from scripts.evaluate_agent import EvalTrace, SourceCheck, load_cases, score


def test_evaluator_counts_emergency_forbidden_sources_latency_and_missing() -> None:
    cases = load_cases(Path(__file__).resolve().parents[2] / "evals/k01_cases.jsonl")
    traces = {
        "e01": EvalTrace(
            id="e01",
            routes=("problem",),
            actions=("urgent_route", "conversation.ask_critical_only"),
            violations=("wait_poll_threshold",),
            latency_ms=100,
            tool_calls=2,
        ),
        "p04": EvalTrace(
            id="p04",
            routes=("problem",),
            actions=("case.search", "separate_locations"),
            latency_ms=300,
            tool_calls=1,
        ),
        "q03": EvalTrace(
            id="q03",
            routes=("question",),
            actions=("knowledge.search", "knowledge.answer"),
            source_checks=(SourceCheck(source_ref="demo:1", reviewed=False, applicable=True),),
            latency_ms=200,
            tool_calls=1,
        ),
    }
    result = score(cases, traces)
    assert result.total == 24 and result.valid_traces == 3
    assert result.emergency_recalled == 0 and result.emergency_total == 4
    assert result.forbidden_case_ids == ("e01",)
    assert result.invalid_source_case_ids == ("q03",)
    assert "e01" in result.critical_failure_ids
    assert "p04" not in result.critical_failure_ids
    assert "x01" in result.critical_failure_ids
    assert result.p50_ms == 200 and result.p95_ms == 300
    assert result.total_tool_calls == 4


def test_claim_without_verified_source_fails_source_check() -> None:
    case = load_cases(Path(__file__).resolve().parents[2] / "evals/k01_cases.jsonl")[0]
    trace = EvalTrace(
        id=case.id,
        routes=case.routes,
        actions=("knowledge.search", "knowledge.answer"),
        latency_ms=1,
        tool_calls=1,
    )
    result = score([case], {case.id: trace})
    assert result.invalid_source_case_ids == (case.id,)


def test_required_alternatives_accept_a_real_action_and_reject_symbolic_label() -> None:
    cases = load_cases(Path(__file__).resolve().parents[2] / "evals/k01_cases.jsonl")
    by_id = {case.id: case for case in cases}
    for case_id, accepted, rejected in (
        ("p01", ("case.search", "case.attach_message"), ("case.search", "case.create_or_attach")),
        ("p03", ("case.search", "conversation.ask"), ("case.search", "case.attach_or_clarify")),
        (
            "p05",
            ("case.search", "case.recurrence.create"),
            ("case.search", "create_recurrence_or_clarify"),
        ),
        ("i01", ("initiative.create",), ("initiative.create_or_clarify",)),
    ):
        case = by_id[case_id]
        good = EvalTrace(
            id=case_id, routes=case.routes, actions=accepted, latency_ms=1, tool_calls=1
        )
        bad = EvalTrace(
            id=case_id, routes=case.routes, actions=rejected, latency_ms=1, tool_calls=1
        )
        assert score([case], {case_id: good}).required_covered == 1
        assert score([case], {case_id: bad}).required_covered == 0
