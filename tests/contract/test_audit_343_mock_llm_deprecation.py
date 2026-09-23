"""TRAIGENT_MOCK_LLM is deprecated, and mock mode does not bypass cost limits.

Traigent/traigent-skills#343 (the parts in the boost-agent and debugging skills).
On traigent 0.27.0 the env var emits a DeprecationWarning that Python hides by
default ("will be removed in a future release"), and the runtime cost enforcer
runs in mock mode too. Recipes that set the env var must say it is deprecated.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Skills this check owns; widen as the other skills that teach the env var are updated.
SCANNED_SKILLS = ("traigent-boost-agent", "traigent-debugging")
# A line that SETS the env var to true (export, inline, YAML env, os.environ, monkeypatch).
SETS_MOCK_LLM = re.compile(
    r"""TRAIGENT_MOCK_LLM\s*[=:]\s*["']?true|"""
    r"""\[["']TRAIGENT_MOCK_LLM["']\]\s*=\s*["']true|"""
    r"""setenv\(\s*["']TRAIGENT_MOCK_LLM["']\s*,\s*["']true""",
    re.IGNORECASE,
)
WINDOW = 8


def test_every_mock_llm_recipe_says_it_is_deprecated() -> None:
    offenders = []
    for skill in SCANNED_SKILLS:
        for path in sorted((ROOT / "skills" / skill).glob("**/*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if not SETS_MOCK_LLM.search(line):
                    continue
                window = "\n".join(lines[max(0, index - WINDOW) : index + WINDOW + 1]).lower()
                if "deprecated" not in window:
                    offenders.append(f"{path.relative_to(ROOT)}:{index + 1}: {line.strip()}")
    assert not offenders, (
        f"TRAIGENT_MOCK_LLM=true taught without 'deprecated' within {WINDOW} lines:\n"
        + "\n".join(offenders)
    )


def test_mock_mode_reference_states_cost_limits_still_apply() -> None:
    text = " ".join(
        (ROOT / "skills" / "traigent-debugging" / "references" / "mock-mode.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert 'stop_reason="cost_limit"' in text
    assert "bypass cost tracking" not in text and "bypasses cost tracking" not in text


def test_mock_run_still_enforces_the_cost_limit(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    (tmp_path / "home").mkdir()
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            """
            import traigent
            from pathlib import Path
            from traigent.testing import enable_mock_mode_for_quickstart

            enable_mock_mode_for_quickstart()
            Path("qa.jsonl").write_text('{"input": {"question": "q"}, "output": "4"}\\n')

            @traigent.optimize(eval_dataset="qa.jsonl", objectives=["accuracy"], offline=True,
                               configuration_space={"model": ["gpt-4o-mini", "gpt-4o"],
                                                    "temperature": [0.1, 0.5]})
            def f(question: str) -> str:
                traigent.get_config()
                return "4"

            r = f.optimize_sync(max_trials=4, algorithm="grid")
            print(f"RESULT={r.stop_reason}|{len(r.trials)}")
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
            "TRAIGENT_RUN_COST_LIMIT": "0.0001",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT="))
    stop_reason, trials = line.removeprefix("RESULT=").split("|")
    assert (stop_reason, trials) == ("cost_limit", "0")
