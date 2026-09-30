import json
from pathlib import Path

import httpx
import pytest

from scripts.evaluate_agent import load_traces
from scripts.run_triage_evals import run


@pytest.mark.asyncio
async def test_route_runner_records_validated_routes_and_failures(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    output = tmp_path / "traces.jsonl"
    dataset.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "id": "ok",
                        "text": "Не горит лампа",
                        "routes": ["problem"],
                        "required_actions": ["case.search"],
                        "forbidden_actions": [],
                        "source_refs": [],
                        "critical": False,
                    }
                ),
                json.dumps(
                    {
                        "id": "bad",
                        "text": "Ошибка ответа",
                        "routes": ["question"],
                        "required_actions": [],
                        "forbidden_actions": [],
                        "source_refs": [],
                        "critical": False,
                    }
                ),
            )
        )
        + "\n"
    )

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        text = body["messages"][-1]["content"]
        content = (
            '{"items":[{"kind":"problem","text":"Не горит лампа",'
            '"entrance":null,"object_name":"лампа"}]}'
            if text == "Не горит лампа"
            else "not-json"
        )
        return httpx.Response(200, json={"message": {"content": content}})

    await run(
        dataset,
        output,
        "https://ollama.test",
        "test-model",
        5.0,
        transport=httpx.MockTransport(respond),
    )

    traces, invalid = load_traces(output)
    assert invalid == 0
    assert traces["ok"].routes == ("problem",)
    assert traces["bad"].violations == ("triage_error:ValueError",)
