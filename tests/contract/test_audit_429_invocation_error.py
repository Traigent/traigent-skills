"""Issue #429: ``InvocationError`` does not catch ordinary per-example failures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DEBUGGING = Path(__file__).resolve().parents[2] / "skills" / "traigent-debugging"


def test_docs_do_not_claim_every_function_exception_is_an_invocation_error() -> None:
    skill = (DEBUGGING / "SKILL.md").read_text(encoding="utf-8")
    ref = (DEBUGGING / "references" / "error-reference.md").read_text(encoding="utf-8")
    assert "The decorated function raised an exception during a trial." not in skill
    assert "**Function raised an exception during a trial.**" not in ref
    assert "Function call failed:" in skill
    assert "propagate as their own type" not in skill
    assert "catches a generic exception from a trial" in skill
    assert "scored-example coverage" in skill and "scored-example coverage" in ref
    assert "print(f\"Original error: {e.original_error}\")" not in skill


_PROBE = """
import json
import traigent
from traigent.utils.exceptions import InvocationError, NonRetryableError

rows = [{"input": {"q": "a"}, "output": "A"}, {"input": {"q": "b"}, "output": "B"}]
with open("qa.jsonl", "w", encoding="utf-8") as handle:
    handle.write("\\n".join(json.dumps(row) for row in rows) + "\\n")

report = {}
for exc_type in (RuntimeError, NonRetryableError, InvocationError):

    @traigent.optimize(
        eval_dataset="qa.jsonl",
        objectives=["accuracy"],
        offline=True,
        configuration_space={"m": ["x"]},
    )
    def answer(q):
        raise exc_type("boom-marker-123")

    results = answer.optimize_sync(max_trials=1, algorithm="grid")  # must return, not raise
    trial = results.trials[0]
    evaluation = (trial.metadata or {}).get("evaluation_result") or {}
    report[exc_type.__name__] = {
        "status": str(trial.status),
        "error_type": trial.error_type,
        "examples": [
            [ex["success"], ex["actual_output"], ex["error_message"]]
            for ex in evaluation.get("example_results", [])
        ],
    }
print("REPORT=" + json.dumps(report))
"""


def test_sdk_turns_ordinary_exceptions_into_per_example_failures(tmp_path: Path) -> None:
    """Behaviour, not source text: an ordinary exception becomes a failed example.

    Released SDKs record ``Function call failed: <message>``; SDK develop records
    ``Function call failed: <ExceptionClass>: <message>``. Both keep the prefix and the
    original text, which is what the skill teaches. Typed SDK errors are not turned into
    per-example failures: they surface as their own type on the failed trial.
    """
    pytest.importorskip("traigent")
    (tmp_path / "home").mkdir()
    (tmp_path / "probe.py").write_text(_PROBE, encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY")
        and not k.startswith("TRAIGENT_")
        and k not in {"CI", "GITHUB_ACTIONS"}
    }
    env.update({"HOME": str(tmp_path / "home"), "TRAIGENT_OFFLINE_MODE": "true",
                "TRAIGENT_MOCK_LLM": "true", "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                "ENVIRONMENT": "test"})
    done = subprocess.run(
        [sys.executable, "probe.py"], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    line = next(ln for ln in done.stdout.splitlines() if ln.startswith("REPORT="))
    report = json.loads(line[len("REPORT="):])

    ordinary = report["RuntimeError"]
    assert ordinary["error_type"] is None, ordinary
    assert len(ordinary["examples"]) == 2, ordinary
    for success, output, message in ordinary["examples"]:
        assert success is False and output is None, ordinary
        assert message.startswith("Function call failed: "), message
        assert message.endswith("boom-marker-123"), message

    for typed in ("NonRetryableError", "InvocationError"):
        assert report[typed]["error_type"] == typed, report[typed]
        assert report[typed]["examples"] == [], report[typed]
