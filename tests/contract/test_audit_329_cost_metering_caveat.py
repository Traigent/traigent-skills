"""Issue #329: multi-call custom evaluators must carry the cost-metering caveat.

On traigent <= 0.29.0 the SDK meters only the first captured LLM response per
row inside a ``custom_evaluator`` (``evaluator_wrapper`` took
``captured_responses[0]``). The statistical, judge and hybrid templates make
several calls per row, so their ``cost`` and ``TRAIGENT_RUN_COST_LIMIT`` saw a
fraction of real spend. The skill says so next to those templates and next to
its cost-limit advice, scoped to that version range.

Traigent 0.30.0 fixed this: every captured LLM call in the row is now metered
(Traigent/Traigent#2441). The second test below pins the SDK behavior the
caveat describes on both sides of that boundary: on traigent <= 0.29.0 the
statistical template must still report the same trial cost at 1 and 5 calls
per row (the bug); on traigent >= 0.30.0 it must report 5x the cost at 5 calls
(the fix), and the doc must name 0.30.0 as the release that fixed it. A
regression in either direction goes red.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

from .test_audit_326_comparator_case import _python_block, _run_driver

SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "traigent-eval-build"
TEMPLATES = SKILL_DIR / "references" / "evaluator-templates.md"
CAVEAT_HEADING = "Cost metering caveat for multi-call evaluators"
FIX_VERSION = "0.30.0"


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"missing section {heading!r}"
    return match.group(1)


def test_caveat_sits_next_to_every_multi_call_template() -> None:
    text = TEMPLATES.read_text(encoding="utf-8")
    caveat = _section(text, CAVEAT_HEADING)
    assert "only the **first**" in caveat and "TRAIGENT_RUN_COST_LIMIT" in caveat
    assert "<!-- contract: literal" in caveat, (
        "the caveat must carry a docstamp so an SDK change re-checks it"
    )
    for heading in (
        "LLM judge with rubric, strict parse, and cost guardrails",
        "Hybrid deterministic gate then judge",
    ):
        assert CAVEAT_HEADING in _section(text, heading), heading
    headings = re.findall(r"^## (.+)$", text, re.MULTILINE)
    assert headings.index(CAVEAT_HEADING) + 1 == headings.index(
        "Statistical agreement over repeated calls"
    ), "the caveat must sit directly above the statistical template"


def test_skill_cost_limit_advice_links_the_caveat() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    advice = next(
        line
        for line in skill.splitlines()
        if "set `TRAIGENT_RUN_COST_LIMIT` before any evaluator" in line
    )
    assert "cost-metering caveat" in advice and "evaluator-templates.md" in advice


def test_sdk_still_meters_only_the_first_call_per_row(
    tmp_path: Path, sdk_version_label: str
) -> None:
    body = """
    install_replies(lambda model, messages: "paris")
    write_rows("qa.jsonl", [{"input": {"question": f"Q{i}?"}, "output": "paris"} for i in range(3)])
    costs = {}
    for reps in (1, 5):
        ns = load_block(sys.argv[1])
        ns["EVAL_REPS"] = reps
        result = ns["answer"].optimize_sync(algorithm="grid", max_trials=1)
        costs[reps] = result.trials[0].metrics.get("cost")
    emit(costs)
    """
    costs = _run_driver(
        tmp_path, _python_block(TEMPLATES, "def statistical_agreement_evaluator"), body
    )
    assert costs["1"] and costs["1"] > 0, costs

    fixed = sdk_version_label == "develop" or Version(sdk_version_label) >= Version(
        FIX_VERSION
    )
    if fixed:
        assert costs["5"] > costs["1"], (
            "the SDK went back to metering only the first LLM call per row in a "
            "custom evaluator: restore the cost-metering caveat in "
            f"evaluator-templates.md (and its SKILL.md pointer). costs={costs}"
        )
        text = TEMPLATES.read_text(encoding="utf-8")
        assert f"fixed in {FIX_VERSION}" in text, (
            f"the doc must name {FIX_VERSION} as the release that fixed multi-call "
            "cost metering"
        )
    else:
        assert costs["5"] == costs["1"], (
            "the SDK now meters more than the first LLM call per row in a custom "
            "evaluator: scope the cost-metering caveat in evaluator-templates.md "
            f"(and its SKILL.md pointer) to traigent <= {sdk_version_label} and name "
            f"the release that fixed it. costs={costs}"
        )
