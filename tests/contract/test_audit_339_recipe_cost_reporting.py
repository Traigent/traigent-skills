"""Boost-agent instrument recipe: the cost the function computes reaches the run.

Traigent/traigent-skills#339 (the instrument-recipe part). The recipe returned its
computed cost under the ``cost`` key of the ``(output, metrics)`` tuple. ``cost`` is
evaluator-reserved, so the SDK dropped it with a "Skipping user metric" WARNING
once per example and ``results.total_cost`` never saw it, in a run whose
objectives are ``["accuracy", "cost"]``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "skills" / "traigent-boost-agent" / "references" / "instrument-recipe.md"
PER_CALL_COST = 0.01
EXAMPLES = 3


def _after_block() -> str:
    section = RECIPE.read_text(encoding="utf-8").split("## After", 1)[1].split("## Environment", 1)[0]
    python = [b.text for b in _iter_fenced_blocks(section.splitlines()) if b.language == "python"]
    assert len(python) == 1
    return python[0]


def test_recipe_cost_reaches_total_cost_without_reserved_key_warning(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    (tmp_path / "evals").mkdir()
    rows = [{"input": {"question": f"q{i}"}, "output": "a"} for i in range(EXAMPLES)]
    (tmp_path / "evals" / "qa.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (tmp_path / "home").mkdir()
    agent = tmp_path / "agent.py"
    agent.write_text(_after_block() + "\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(
        textwrap.dedent(
            f"""
            import builtins, json, runpy
            from traigent.testing import enable_mock_mode_for_quickstart
            enable_mock_mode_for_quickstart()
            builtins.retrieve_context = lambda question, **kw: ["context"]
            builtins.format_context = lambda chunks, **kw: "context"
            builtins.estimate_last_call_cost_usd = lambda: {PER_CALL_COST!r}
            ns = runpy.run_path({str(agent)!r}, run_name="recipe_under_test")
            result = ns["answer_question"].optimize_sync(max_trials=1, algorithm="grid")
            print("RESULT=" + json.dumps({{
                "total_cost": result.total_cost,
                "trial_cost": result.trials[0].metrics.get("cost"),
                "failed": len(getattr(result, "failed_trials", []) or []),
            }}))
            """
        ),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k not in {"TRAIGENT_MOCK_LLM", "CI", "GITHUB_ACTIONS"}
    }
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
            # Only so an older raw-client recipe can import; the mocked run makes no call.
            "OPENAI_API_KEY": "sk-test-not-a-real-key",
            "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(runner)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=240, check=False,
    )
    log = completed.stdout + completed.stderr
    assert completed.returncode == 0, log
    assert "Skipping user metric 'cost'" not in log, "the recipe's cost is dropped as a reserved key"
    result = json.loads(
        next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT=")).removeprefix("RESULT=")
    )
    assert result["failed"] == 0, log[-3000:]
    assert result["total_cost"] == pytest.approx(PER_CALL_COST * EXAMPLES), result
