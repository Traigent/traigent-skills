"""Boost-agent must not present ``BaseEvaluator`` as a wireable scorer.

Traigent/traigent-skills#331 (the boost-agent siblings). On traigent 0.27.0 a
``BaseEvaluator`` cannot be wired through ``@traigent.optimize``: an instance
passed as ``custom_evaluator`` makes the run raise ``ValueError: custom_evaluator
must be callable``, and ``evaluator=`` accepts only external-service evaluators. The
boost-agent ladder and its symptom table still sent readers to that rung.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "traigent-boost-agent"
NOT_WIREABLE = "not wireable"


def _unit(lines: list[str], index: int) -> str:
    """The paragraph, list item or table row that holds ``lines[index]``."""
    line = lines[index]
    if line.lstrip().startswith("|"):
        return line
    lo = index
    while lo > 0 and lines[lo - 1].strip() and not lines[lo - 1].lstrip().startswith(("#", "- ", "|")):
        if lines[lo].lstrip().startswith("- "):
            break
        lo -= 1
    hi = index
    while hi + 1 < len(lines) and lines[hi + 1].strip() and not lines[hi + 1].lstrip().startswith(("#", "- ", "|")):
        hi += 1
    return "\n".join(lines[lo : hi + 1])


def test_base_evaluator_is_only_mentioned_as_not_wireable() -> None:
    offenders = []
    for path in sorted(SKILL_DIR.glob("**/*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "BaseEvaluator" in line and NOT_WIREABLE not in _unit(lines, index):
                offenders.append(f"{path.relative_to(ROOT)}:{index + 1}: {line.strip()[:120]}")
    assert not offenders, (
        "BaseEvaluator presented as a wireable scorer (say it is not wireable on the "
        "released SDK, or drop it):\n" + "\n".join(offenders)
    )


def test_wire_first_ladder_ends_at_custom_evaluator() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    ladder = next(line for line in text.splitlines() if "wire-first ladder" in line)
    rungs = [part.strip(" `.") for part in ladder.split(":", 1)[1].split("(")[0].split("->")]
    assert rungs[-1] == "custom_evaluator", rungs


def test_base_evaluator_instance_cannot_be_wired_on_the_installed_sdk(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    (tmp_path / "home").mkdir()
    (tmp_path / "qa.jsonl").write_text('{"input": {"q": "a"}, "output": "A"}\n', encoding="utf-8")
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            """
            import traigent
            from traigent.evaluators.base import BaseEvaluator

            class Scorer(BaseEvaluator):
                async def evaluate(self, func, config, dataset, **kwargs):
                    raise AssertionError("never reached")

            try:
                @traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                                   configuration_space={"m": ["x"]}, custom_evaluator=Scorer())
                def answer(q):
                    traigent.get_config()
                    return q.upper()

                answer.optimize_sync(max_trials=1, algorithm="grid")
            except ValueError as exc:
                print("RESULT=" + str(exc))
            else:
                print("RESULT=wired")
            """
        ),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k not in {"TRAIGENT_MOCK_LLM", "CI", "GITHUB_ACTIONS"}
    }
    env.update({"HOME": str(tmp_path / "home"), "TRAIGENT_OFFLINE_MODE": "true",
                "LITELLM_LOCAL_MODEL_COST_MAP": "True", "ENVIRONMENT": "test"})
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT="))
    # If a future SDK wires it, this pin goes red: update the skill then.
    assert result == "RESULT=custom_evaluator must be callable", result
