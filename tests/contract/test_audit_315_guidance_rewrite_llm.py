"""The Mode C weak-examples snippet must pass the required ``rewrite_llm`` (#315).

``optimize_with_guidance()`` refuses to build a rewrite model from environment
credentials and raises ``GenerationProviderError`` before anything runs when
``rewrite_llm`` is missing. This test executes the SKILL's fenced block,
verbatim, on the installed SDK in mock mode with a stub ``provider`` and a stub
``answer`` function, and asserts the call gets past argument resolution: it
reaches the provider, which raises a sentinel instead of returning a plan.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SKILL = Path("skills/traigent-analyze-guidance/SKILL.md")
FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
SENTINEL = "STUB_PROVIDER_REACHED"


def _snippet(repo_root: Path) -> str:
    text = (repo_root / SKILL).read_text(encoding="utf-8")
    blocks = [b for b in FENCE_RE.findall(text) if "optimize_with_guidance(" in b]
    assert len(blocks) == 1, f"{SKILL}: expected one optimize_with_guidance block"
    return blocks[0]


def test_weak_examples_snippet_supplies_rewrite_llm(
    repo_root: Path, tmp_path: Path
) -> None:
    pytest.importorskip("traigent")
    script = tmp_path / "guided.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import traigent
            from traigent.testing import enable_mock_mode_for_quickstart

            enable_mock_mode_for_quickstart()  # no provider calls, no pricing preflight

            with open("eval.jsonl", "w") as fh:
                for i in range(4):
                    fh.write(json.dumps({"input": {"text": f"q{i}"}, "output": f"a{i}"}) + "\\n")

            @traigent.optimize(
                eval_dataset="eval.jsonl", objectives=["accuracy"], algorithm="grid",
                max_trials=2, offline=True, configuration_space={"model": ["small", "large"]},
            )
            def answer(text):
                return "a" + text[1:]

            class StubProvider:
                def __getattr__(self, name):
                    raise RuntimeError("%s")

            provider = StubProvider()
            """
        )
        % SENTINEL
        + _snippet(repo_root),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith("_API_KEY") and key != "TRAIGENT_MOCK_LLM"
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
    assert "requires an explicit rewrite_llm" not in output, output
    assert SENTINEL in output, (
        f"expected the call to reach the provider; exit={completed.returncode}\n{output}"
    )


def test_prose_states_rewrite_llm_is_required_and_keeps_the_paid_run_gate(
    repo_root: Path,
) -> None:
    text = " ".join((repo_root / SKILL).read_text(encoding="utf-8").split())
    assert "`rewrite_llm` is required" in text
    assert (
        "This is a **paid real run** — the same gate as any other applies: dry-run/mock first, "
        "present the cost estimate, and get explicit user approval before executing"
    ) in text
