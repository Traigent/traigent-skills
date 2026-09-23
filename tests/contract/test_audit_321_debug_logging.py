"""Debugging skill: the Quick Diagnostic must turn on Traigent debug output on a decorated run.

Traigent/traigent-skills#321. The skill's first step was ``export
TRAIGENT_LOG_LEVEL=DEBUG``. The SDK applies that variable only when
``traigent.configure(logging_level=...)``, ``traigent.initialize()`` or the CLI
sets up logging, so a script that only uses ``@traigent.optimize`` got no
``traigent.*`` debug lines at all.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "traigent-debugging" / "SKILL.md"


def _quick_diagnostic_python() -> str:
    section = SKILL.read_text(encoding="utf-8").split("## Quick Diagnostic", 1)[1].split("\n## ", 1)[0]
    python = [b.text for b in _iter_fenced_blocks(section.splitlines()) if b.language == "python"]
    assert python, "Quick Diagnostic has no Python step that enables SDK logging"
    return python[0]


def test_quick_diagnostic_produces_traigent_debug_lines_on_a_decorated_run(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    diagnostic = _quick_diagnostic_python()
    (tmp_path / "home").mkdir()
    (tmp_path / "eval_data.jsonl").write_text(
        "".join(f'{{"input": "q{i}", "output": "a"}}\n' for i in range(4)), encoding="utf-8"
    )
    script = tmp_path / "run.py"
    script.write_text(
        diagnostic
        + "\n"
        + textwrap.dedent(
            """
            from traigent.testing import enable_mock_mode_for_quickstart
            enable_mock_mode_for_quickstart()

            @traigent.optimize(eval_dataset="eval_data.jsonl", configuration_space={"model": ["a", "b"]},
                               objectives=["accuracy"], offline=True)
            def f(text):
                return traigent.get_config()["model"]

            f.optimize_sync(max_trials=2, algorithm="grid")
            """
        ),
        encoding="utf-8",
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k not in {"TRAIGENT_MOCK_LLM", "TRAIGENT_LOG_LEVEL", "CI", "GITHUB_ACTIONS"}
    }
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
        }
    )
    completed = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, text=True,
        capture_output=True, timeout=180, check=False,
    )
    log = completed.stdout + completed.stderr
    assert completed.returncode == 0, log
    assert re.search(r" - traigent\.core\.[a-z_.]+ - DEBUG - ", log), log[-2000:]


def test_skill_does_not_teach_the_env_var_alone_as_the_debug_switch() -> None:
    for path in (SKILL, ROOT / "skills" / "traigent-debugging" / "references" / "logging-config.md"):
        text = path.read_text(encoding="utf-8")
        assert "read on all current SDK versions" not in text, path.name
        assert "traigent.configure(logging_level=" in text, path.name
