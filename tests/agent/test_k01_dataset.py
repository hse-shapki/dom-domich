from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def test_k01_dataset_has_all_routes_and_adversarial_cases() -> None:
    path = Path(__file__).resolve().parents[2] / "evals" / "k01_cases.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    ids = [row["id"] for row in rows]
    assert len(rows) == len(set(ids)) == 24
    assert Counter(route for row in rows for route in row["routes"]) == {
        "problem": 9,
        "question": 6,
        "conversation": 4,
        "emergency": 4,
        "initiative": 4,
    }
    for row in rows:
        assert isinstance(row["text"], str) and row["text"]
        assert row["routes"]
        assert set(row) == {
            "id",
            "text",
            "routes",
            "required_actions",
            "forbidden_actions",
            "source_refs",
            "critical",
        }
        if row["id"].startswith("x"):
            assert row["critical"]
            assert any("instructions" in action for action in row["forbidden_actions"])
