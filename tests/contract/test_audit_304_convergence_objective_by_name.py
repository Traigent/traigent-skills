"""The convergence reference must read each trial's objective by name (part of #304).

On SDKs after 0.21.3, ``trial.metrics["score"]`` equals the objective only for a single
built-in objective; a weighted multi-objective run records its normalised selection basis
there. This test runs the reference's ``best_score_curve`` verbatim on a real offline
multi-objective run and checks the curve tracks accuracy, not ``score``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REFERENCE = Path("skills/traigent-analyze-results/references/convergence-patterns.md")
FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def test_reference_code_never_reads_score_as_the_objective(repo_root: Path) -> None:
    text = (repo_root / REFERENCE).read_text(encoding="utf-8")
    for block in FENCE_RE.findall(text):
        assert 'metrics.get("score")' not in block
        assert 'metrics["score"]' not in block


def test_best_score_curve_tracks_the_objective_on_a_multi_objective_run(
    repo_root: Path, tmp_path: Path
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
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k != "TRAIGENT_MOCK_LLM"
    }
    env.update(
        {"HOME": str(home), "ENVIRONMENT": "test", "TRAIGENT_OFFLINE_MODE": "true"}
    )
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
    assert "SCORE_DIFFERS=True" in output, output  # the fixture exercises the defect
    assert "CURVE_OK=True" in output, output
