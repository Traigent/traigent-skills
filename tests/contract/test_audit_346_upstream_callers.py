"""Contract test: the upstream skill-contract callers are tokenless and fail closed.

``docs/keeping-skills-in-sync.md`` and the reusable
``skill-contract-upstream.yml`` are how an upstream repository wires this
repo's contract into its own PR CI. A caller that needs a secret to read this
public repo, gates a step on the ``secrets`` context (which GitHub rejects in a
step ``if:``), or turns a missing token into a green skip reports success for a
contract that never ran.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "docs" / "keeping-skills-in-sync.md"
REUSABLE = REPO_ROOT / ".github" / "workflows" / "skill-contract-upstream.yml"
TEMPLATE = REPO_ROOT / ".github" / "upstream-templates" / "traigent-sdk-caller.yml"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def _guide_callers() -> list[str]:
    return re.findall(r"```yaml\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for job in workflow["jobs"].values() for s in job.get("steps", [])]


def test_guide_ships_caller_templates() -> None:
    assert _guide_callers(), "the guide lost its caller templates"


@pytest.mark.parametrize("index", range(len(_guide_callers())))
def test_guide_caller_needs_no_secret_and_pins_actions(index: int) -> None:
    text = _guide_callers()[index]
    assert "secrets." not in text, "reading the public skills repo needs no secret"
    for step in _steps(yaml.safe_load(text)):
        uses = step.get("uses")
        if uses:
            assert PINNED.match(uses), f"{uses} is not pinned to a commit SHA"
        if str(uses or "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False
            assert "token" not in step["with"]
        assert "if" not in step, "a step gate can turn the caller into a green no-op"


def test_reusable_workflow_has_no_skip_path_and_no_secret() -> None:
    workflow = yaml.safe_load(REUSABLE.read_text(encoding="utf-8"))
    # PyYAML reads the bare `on:` key as boolean True.
    trigger = workflow.get("on", workflow.get(True))
    assert not (trigger["workflow_call"] or {}).get("secrets")
    steps = _steps(workflow)
    assert all("if" not in step for step in steps), "every step must always run"
    skills = [s for s in steps if s.get("with", {}).get("repository") == "Traigent/traigent-skills"]
    assert len(skills) == 1
    assert "token" not in skills[0]["with"]
    assert skills[0]["with"]["ref"] == "main"
    for step in steps:
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False
    assert "python -m pytest" in steps[-1]["run"]


def test_caller_template_passes_no_secret() -> None:
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    for job in template["jobs"].values():
        assert "secrets" not in job
    assert "secrets." not in TEMPLATE.read_text(encoding="utf-8")
