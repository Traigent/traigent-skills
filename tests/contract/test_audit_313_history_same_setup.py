"""The run-history comparison guard in traigent-analyze-results must fire (#313).

``OptimizationResult.metadata`` carries no ``configuration_space`` key, so a
guard that compares ``metadata.get("configuration_space")`` is ``None == None``
and passes for runs on different spaces. This test executes the SKILL's
fenced comparison block, verbatim, after two real offline runs on the
installed SDK: one pair with different spaces must read ``False`` and one
pair with the same space must read ``True``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .test_runnable_snippets import _offline_mock_env

SKILL = Path("skills/traigent-analyze-results/SKILL.md")
FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _comparison_block(repo_root: Path) -> str:
    text = (repo_root / SKILL).read_text(encoding="utf-8")
    blocks = [block for block in FENCE_RE.findall(text) if "same_setup" in block]
    assert len(blocks) == 1, f"{SKILL}: expected one fenced block computing same_setup"
    return blocks[0]


def _offline_env(home: Path) -> dict[str, str]:
    # The shared offline env strips keys and CI markers (the SDK's CI-approval
    # gate otherwise refuses even mock/offline runs on a CI runner).
    env = _offline_mock_env()
    env.pop("TRAIGENT_MOCK_LLM", None)
    env["HOME"] = str(home)
    return env


def test_history_guard_detects_a_different_search_space(
    repo_root: Path, tmp_path: Path
) -> None:
    pytest.importorskip("traigent")
    block = _comparison_block(repo_root)
    script = tmp_path / "history.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import traigent
            from traigent.testing import enable_mock_mode_for_quickstart

            enable_mock_mode_for_quickstart()  # no provider calls, no pricing preflight

            with open("eval.jsonl", "w") as fh:
                for i in range(10):
                    fh.write(json.dumps({"input": {"text": f"q{i}"}, "output": f"a{i}"}) + "\\n")

            @traigent.optimize(
                eval_dataset="eval.jsonl", objectives=["accuracy"], algorithm="grid",
                max_trials=4, offline=True,
                configuration_space={"model": ["small", "large"], "temperature": [0.0, 0.5]},
            )
            def classify(text):
                return "a" + text[1:] if traigent.get_config()["model"] == "large" else "wrong"

            BLOCK = %r
            verdicts = {}
            classify.optimize_sync()
            classify.optimize_sync(
                configuration_space={"model": ["small"], "temperature": [0.0, 0.2]}, max_trials=2
            )
            exec(BLOCK)
            verdicts["different_space"] = same_setup
            classify.optimize_sync(
                configuration_space={"model": ["small"], "temperature": [0.0, 0.2]}, max_trials=2
            )
            exec(BLOCK)
            verdicts["same_space"] = same_setup
            print("VERDICTS=" + json.dumps(verdicts))
            """
        )
        % block,
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=_offline_env(home),
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(
        line for line in completed.stdout.splitlines() if line.startswith("VERDICTS=")
    )
    verdicts = json.loads(line.removeprefix("VERDICTS="))
    assert verdicts == {"different_space": False, "same_space": True}, verdicts


def test_prose_does_not_name_a_result_field_that_does_not_exist(
    repo_root: Path,
) -> None:
    text = (repo_root / SKILL).read_text(encoding="utf-8")
    assert 'metadata["configuration_space"]' not in text
    assert 'metadata.get("configuration_space")' not in text


def test_configuration_insights_names_the_guidance_modes(repo_root: Path) -> None:
    text = " ".join((repo_root / SKILL).read_text(encoding="utf-8").split())
    assert (
        "`traigent-analyze-guidance` for portal-tracked runs or `traigent-analyze-guidance`"
        not in text
    )
    assert (
        "`traigent-analyze-guidance` (Mode B for portal-tracked runs, Mode C for offline/local runs)"
        in text
    )
