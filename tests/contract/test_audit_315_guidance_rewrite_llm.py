"""The Mode C weak-examples snippet must be a call that runs and uses its inputs.

#315: ``optimize_with_guidance()`` refuses to build a rewrite model from environment
credentials and raises ``GenerationProviderError`` before anything runs when
``rewrite_llm`` is missing.

#334: ``weak_examples`` are read only by a ``plan_kind="prompt_rewrite"`` plan with a
``prompt_param``; under the default ``benchmark_guide`` plan they are silently ignored.

Both tests execute the SKILL's fenced block, verbatim, on the installed SDK in mock
mode against a stub ``answer`` function:

* with a stub provider that raises a sentinel, the call gets past argument
  resolution and reaches the provider;
* with a provider that returns an empty prompt-rewrite plan and a recording rewrite
  model, the weak example's input reaches the rewrite model's prompt.
"""

from __future__ import annotations

import ast
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

PRELUDE = """
import json
import traigent
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()  # no provider calls, no pricing preflight

with open("eval.jsonl", "w") as fh:
    for i in range(4):
        fh.write(json.dumps({"input": {"text": f"q{i}"}, "output": f"a{i}"}) + "\\n")

@traigent.optimize(
    eval_dataset="eval.jsonl", objectives=["accuracy"], algorithm="grid",
    max_trials=2, offline=True,
    configuration_space={"model": ["small", "large"], "system_prompt": ["Answer briefly."]},
)
def answer(text):
    return "a" + text[1:]
"""


def _snippet(repo_root: Path) -> str:
    text = (repo_root / SKILL).read_text(encoding="utf-8")
    blocks = [b for b in FENCE_RE.findall(text) if "optimize_with_guidance(" in b]
    assert len(blocks) == 1, f"{SKILL}: expected one optimize_with_guidance block"
    return blocks[0]


def _run(tmp_path: Path, source: str) -> str:
    script = tmp_path / "guided.py"
    script.write_text(source, encoding="utf-8")
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
    return f"exit={completed.returncode}\n{completed.stdout}{completed.stderr}"


def test_weak_examples_snippet_supplies_rewrite_llm(
    repo_root: Path, tmp_path: Path
) -> None:
    pytest.importorskip("traigent")
    source = (
        PRELUDE
        + textwrap.dedent(
            """
            class StubProvider:
                def __getattr__(self, name):
                    raise RuntimeError("%s")

            provider = StubProvider()
            """
        )
        % SENTINEL
        + _snippet(repo_root)
    )
    output = _run(tmp_path, source)
    assert "requires an explicit rewrite_llm" not in output, output
    assert SENTINEL in output, f"expected the call to reach the provider\n{output}"


def test_weak_examples_reach_the_rewrite_model(repo_root: Path, tmp_path: Path) -> None:
    """Run the snippet's setup, swap in a recording rewrite model, then run its call."""
    pytest.importorskip("traigent")
    snippet = _snippet(repo_root)
    body = ast.parse(snippet).body
    setup = "\n".join(ast.get_source_segment(snippet, node) or "" for node in body[:-1])
    call = ast.get_source_segment(snippet, body[-1]) or ""
    assert "optimize_with_guidance(" in call, (
        "the snippet must end with the guided call"
    )
    source = (
        PRELUDE
        + textwrap.dedent(
            """
            from traigent.generation.models import GuidancePlan, PlanKind

            class EmptyPlanProvider:
                def get_guidance_plan(self, request):
                    return GuidancePlan(
                        plan_id="p", policy_version="v", plan_kind=request.plan_kind,
                        items=[], plan_token="t", expires_at="2099-01-01T00:00:00Z",
                    )

            provider = EmptyPlanProvider()
            """
        )
        + setup
        + textwrap.dedent(
            """

            SEEN = []

            def my_rewrite_llm(prompt):
                SEEN.append(prompt)
                return json.dumps(["Answer the question precisely."])

            """
        )
        + call
        + '\nprint("WEAK_EXAMPLE_SEEN=" + str(any("question text" in p for p in SEEN)))\n'
    )
    output = _run(tmp_path, source)
    assert "WEAK_EXAMPLE_SEEN=True" in output, output


def test_prose_states_rewrite_llm_is_required_and_keeps_the_paid_run_gate(
    repo_root: Path,
) -> None:
    text = " ".join((repo_root / SKILL).read_text(encoding="utf-8").split())
    assert "`rewrite_llm` is required" in text
    assert "`weak_examples` are `(input, expected, actual)` tuples" in text
    assert (
        "This is a **paid real run** — the same gate as any other applies: dry-run/mock first, "
        "present the cost estimate, and get explicit user approval before executing"
    ) in text
