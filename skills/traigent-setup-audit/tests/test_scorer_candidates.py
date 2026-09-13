"""Which functions count as scorers, and how repeated lines are collapsed.

Every case in ``FALSE_POSITIVES`` was reported as a scorer by the first version
of this audit on a real project (103 Python files, 2026-09-13): four validators
and test helpers plus one pytest fixture. Each one is pinned here by the shape
that produced it, so the rule cannot quietly regress.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()


# (function name, parameters, path, expected skip reason) — all seen on the
# real project, none of them a scorer.
FALSE_POSITIVES = [
    (
        "check_instruction_id",
        ["body", "expected"],
        "director/protocol/validate.py",
        audit.SKIP_WEAK_MATCH,
    ),
    (
        "check_stage",
        ["body", "expected"],
        "director/protocol/validate.py",
        audit.SKIP_WEAK_MATCH,
    ),
    (
        "_mcp_registration_ok",
        ["seen", "expected", "prefix"],
        "harness/smoke_agents.py",
        audit.SKIP_PRIVATE,
    ),
    (
        "_read_lines_once_settled",
        ["broker", "expected", "timeout_s"],
        "tests/test_broker.py",
        audit.SKIP_PRIVATE,
    ),
    (
        "scorecards",
        ["tmp_path_factory"],
        "tests/test_assess.py",
        audit.SKIP_TEST_FILE,
    ),
]


@pytest.mark.parametrize(
    "name,parameters,path,reason",
    FALSE_POSITIVES,
    ids=[case[0] for case in FALSE_POSITIVES],
)
def test_known_false_positives_are_excluded_with_a_reason(
    name: str, parameters: list[str], path: str, reason: str
) -> None:
    is_candidate, skip_reason = audit.scorer_candidate_verdict(name, parameters, path)
    assert is_candidate is False
    assert skip_reason == reason


# (function name, parameters, path) — real scorers that must survive.
TRUE_POSITIVES = [
    ("evaluate", ["row", "db_path"], "experiments/E1/handoff/evaluator/evaluator.py"),
    ("grade_item", ["item"], "assessor_dev/grader/sqlgrade.py"),
    ("score", ["output", "expected"], "scorer.py"),
    ("exact_match_score", ["a", "b"], "agent.py"),
    ("metric_latency", ["trial"], "agent.py"),
    # Signature-only, but `output` first is the SDK's own binding contract.
    ("compare", ["output", "expected"], "app/util.py"),
    # Signature-only, but the module is named like an evaluator.
    ("compare", ["candidate", "expected"], "app/evaluator.py"),
]


@pytest.mark.parametrize(
    "name,parameters,path", TRUE_POSITIVES, ids=[f"{c[0]}-{c[2]}" for c in TRUE_POSITIVES]
)
def test_real_scorers_survive_the_filter(
    name: str, parameters: list[str], path: str
) -> None:
    is_candidate, skip_reason = audit.scorer_candidate_verdict(name, parameters, path)
    assert is_candidate is True, skip_reason


def test_a_function_that_never_matched_is_not_counted_as_skipped() -> None:
    """Only near-misses are counted on the card; ordinary code is not."""
    assert audit.scorer_candidate_verdict("main", ["argv"], "app.py") == (False, None)


def test_repeated_not_run_lines_collapse_to_one_line_per_kind() -> None:
    candidates = [
        audit.ScorerCandidate(
            function="evaluate",
            file=f"experiments/E{index}/evaluator.py",
            line=index,
            kind="executing",
            signals=["uses sqlite3"],
            parameters=["row"],
        )
        for index in range(1, 15)
    ] + [
        audit.ScorerCandidate(
            function="judge",
            file="app/judge.py",
            line=3,
            kind="llm-judge",
            signals=["imports openai"],
            parameters=["output", "expected"],
        )
    ]
    lines = audit.not_run_lines(candidates)
    assert len(lines) == 2, lines
    executing = next(line for line in lines if "executing" in line)
    assert executing.startswith("14 scorer(s) classified executing were not run")
    assert "uses sqlite3 ×14" in executing
    assert "and 11 more" in executing
    assert "a executing" not in executing  # grammar regression from the first run
    judge = next(line for line in lines if "LLM-judge" in line)
    assert judge.startswith("1 scorer(s) classified LLM-judge were not run")
    assert "this audit makes no provider calls" in judge


def test_skipped_candidates_collapse_to_one_counted_line() -> None:
    skipped = [
        audit.SkippedScorer("_helper", "a.py", 1, audit.SKIP_PRIVATE),
        audit.SkippedScorer("_other", "b.py", 2, audit.SKIP_PRIVATE),
        audit.SkippedScorer("scorecards", "tests/test_x.py", 3, audit.SKIP_TEST_FILE),
    ]
    lines = audit.skipped_scorer_lines(skipped)
    assert len(lines) == 1
    assert lines[0].startswith("skipped 3 function(s)")
    assert "2 with a name starting with `_`" in lines[0]
    assert "1 with a test-file path" in lines[0]
    assert audit.skipped_scorer_lines([]) == []


def test_the_fixture_tree_reports_its_skipped_helper(tmp_path: Path) -> None:
    """End-to-end: the `skipped` fixture's near-misses reach card and JSON."""
    import json
    import subprocess

    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "audit_project.py"),
            "--root",
            str(FIXTURES / "skipped"),
            "--json",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    skipped = {item["function"]: item["reason"] for item in report["skipped_scorer_candidates"]}
    assert skipped == {
        "_private_helper": audit.SKIP_PRIVATE,
        "check_stage": audit.SKIP_WEAK_MATCH,
        "scorecards": audit.SKIP_TEST_FILE,
    }
    # The one real scorer in the tree is still reported.
    assert [item["function"] for item in report["scorers"]] == ["score"]
    assert "skipped 3 function(s)" in completed.stdout
