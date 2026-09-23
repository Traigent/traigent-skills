"""The convergence reference must read each trial's objective by name (part of #304).

On SDKs after 0.21.3, ``trial.metrics["score"]`` equals the objective only for a single
built-in objective; a weighted multi-objective run records its normalised selection basis
there. This test runs the reference's ``best_score_curve`` verbatim on a real offline
multi-objective run and checks the curve tracks accuracy, not ``score``.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .test_runnable_snippets import _offline_mock_env

REFERENCE = Path("skills/traigent-analyze-results/references/convergence-patterns.md")
FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def test_reference_code_never_reads_score_as_the_objective(repo_root: Path) -> None:
    text = (repo_root / REFERENCE).read_text(encoding="utf-8")
    for block in FENCE_RE.findall(text):
        assert 'metrics.get("score")' not in block
        assert 'metrics["score"]' not in block


def test_best_score_curve_tracks_the_objective_on_a_multi_objective_run(
    repo_root: Path, tmp_path: Path, sync_map: dict, sdk_version_label: str
) -> None:
    pytest.importorskip("traigent")
    text = (repo_root / REFERENCE).read_text(encoding="utf-8")
    helper = next(b for b in FENCE_RE.findall(text) if "def best_score_curve" in b)
    script = tmp_path / "curve.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import traigent
            from traigent.testing import enable_mock_mode_for_quickstart

            enable_mock_mode_for_quickstart()
            with open("qa.jsonl", "w") as fh:
                for q, a in [("a", "A"), ("b", "B"), ("c", "C")]:
                    fh.write(json.dumps({"input": {"q": q}, "output": a}) + "\\n")

            def answer(q):
                m = traigent.get_config()["m"]
                return q.upper() if (q != "c" or m == "y") else "wrong"

            fn = traigent.optimize(
                configuration_space={"m": ["x", "y"]}, algorithm="grid", offline=True,
                max_trials=2, objectives=["accuracy", "cost"], eval_dataset="qa.jsonl",
            )(answer)
            results = fn.optimize_sync()
            """
        )
        + helper
        + textwrap.dedent(
            """
            accuracy = [t.metrics["accuracy"] for t in results.trials]
            score = [t.metrics["score"] for t in results.trials]
            expected, best = [], None
            for value in accuracy:
                best = value if best is None else max(best, value)
                expected.append(best)
            print("SCORE_DIFFERS=" + str(score != accuracy))
            print("CURVE_OK=" + str(best_score_curve(results) == expected))
            """
        ),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    # The shared offline env strips CI markers: the SDK's CI-approval gate
    # otherwise refuses even mock/offline runs on a CI runner.
    env = _offline_mock_env()
    env.pop("TRAIGENT_MOCK_LLM", None)
    env["HOME"] = str(home)
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert "CURVE_OK=True" in output, output
    # The fixture only exercises the defect where score is relocated: on 0.21.3
    # score still equals accuracy, so pin the precondition to the current
    # released SDK and develop, the way test_audit_304_score_relocation does.
    current = str(sync_map["current_released_sdk_version"])
    if sdk_version_label in (current, "develop"):
        assert "SCORE_DIFFERS=True" in output, output


def test_custom_scorer_clause_is_scoped_to_its_own_objective_name(
    repo_root: Path,
) -> None:
    text = " ".join((repo_root / REFERENCE).read_text(encoding="utf-8").split())
    assert (
        "a run with a custom `scoring_function` records the built-in exact-match value"
        not in text
    )
    assert "a custom scorer registered under its own objective name" in text
