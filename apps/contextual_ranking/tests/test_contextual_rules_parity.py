"""The Python rules must match the JavaScript that runs on the page."""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from contextual_ranking.rules import analyze_occurrences, rank_following, sort_occurrences
from contextual_ranking.tests.fixtures import (
    PRODUCTION_CURRENT_CONTEXT, PRODUCTION_SEQUENCE, production_occurrences, random_case,
)

REFERENCE = Path(__file__).with_name("js_reference.mjs")
NODE = shutil.which("node")


def python_result(case: dict) -> dict:
    rows = analyze_occurrences(case["current_context"], case["occurrences"])
    ordered = sort_occurrences(rows, case["sequence"], case.get("live", ()), case.get("selected", ()))
    ranked = rank_following(ordered[:case.get("top", 4)])
    return {
        "order": [row["index"] for row in ordered],
        "scores": [[row["score"]["valid"], row["score"]["score"], row["score"]["exact"],
                    row["score"]["neighbor"], row["score"]["similarity"]] if row["score"] else None
                   for row in rows],
        "approved": [row["approved"] for row in rows],
        "ranking": [[row["number"], row["score"], row["exact"], row["neighbor"], row["percentage"]]
                    for row in ranked["ranking"]],
        "analyzed_results": ranked["analyzed_results"],
        "maximum": ranked["maximum"],
    }


def javascript_results(cases: list[dict]) -> list[dict]:
    completed = subprocess.run(
        [NODE, str(REFERENCE)], input=json.dumps({"cases": cases}),
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js é necessário para executar as regras da página")
def test_python_rules_match_page_javascript_on_random_tables():
    rng = random.Random(20261113)
    cases = [random_case(rng) for _ in range(300)]
    cases.append({"current_context": PRODUCTION_CURRENT_CONTEXT, "sequence": PRODUCTION_SEQUENCE,
                  "live": [], "selected": [], "occurrences": production_occurrences()})
    cases.append({"current_context": PRODUCTION_CURRENT_CONTEXT, "sequence": PRODUCTION_SEQUENCE,
                  "live": [16, 27, 8], "selected": [], "occurrences": production_occurrences()})
    expected = javascript_results(cases)
    for index, (case, reference) in enumerate(zip(cases, expected, strict=True)):
        assert python_result(case) == reference, f"divergência no caso {index}"
