"""Issue #468: teach ``agent_name`` as the identity key and ``run_title`` as the run label.

SDK 0.27.0+ marks ``experiment_name`` a deprecated alias of ``agent_name`` (``agent_name``
wins when both are given) and adds ``run_title`` / ``run_description`` for "what this run
is testing". The skills taught the alias as the key and said a per-run label was
impossible. Every surviving ``experiment_name`` mention must be a deprecated-alias
explanation, and no runnable/fenced example may teach it.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from packaging.version import Version

DECORATOR = "skills/traigent-setup-decorator"


def _markdown(root: Path) -> list[Path]:
    return sorted((root / "skills").rglob("*.md"))


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"^```.*?^```", text, re.M | re.S)]


def test_no_fenced_example_teaches_experiment_name(repo_root: Path) -> None:
    offenders = []
    for path in _markdown(repo_root):
        text = path.read_text(encoding="utf-8")
        for start, end in _fenced_spans(text):
            if "experiment_name" in text[start:end]:
                offenders.append(f"{path.relative_to(repo_root)}@{start}")
    assert not offenders, offenders


def test_every_experiment_name_mention_is_a_deprecated_alias_explanation(
    repo_root: Path,
) -> None:
    offenders = []
    for path in _markdown(repo_root):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"experiment_name", text):
            window = text[max(0, match.start() - 400) : match.end() + 400].lower()
            if "deprecated" not in window:
                offenders.append(f"{path.relative_to(repo_root)}@{match.start()}")
    assert not offenders, offenders


def test_setup_decorator_teaches_the_new_names(repo_root: Path) -> None:
    text = " ".join((repo_root / DECORATOR / "SKILL.md").read_text(encoding="utf-8").split())
    assert "Not a decorator argument" not in text
    assert "`agent_name` is the identity key" in text
    assert "`run_title=`" in text and "`run_description=`" in text
    assert "`agent_name` wins" in text
    assert (
        "explicit `agent_name` decorator argument; the deprecated `experiment_name` decorator argument; "
        "`TRAIGENT_EXPERIMENT_NAME`"
    ) in text
    assert "SDKs before 0.27.0" in text


def test_reference_has_runnable_shape_and_is_indexed(repo_root: Path) -> None:
    skill = (repo_root / DECORATOR / "SKILL.md").read_text(encoding="utf-8")
    ref = (repo_root / DECORATOR / "references/agent-identity.md").read_text(encoding="utf-8")
    assert "references/agent-identity.md" in skill
    assert "Requires `traigent>=0.27.0`" in ref
    assert "agent_name=" in ref and "run_title=" in ref and "run_description=" in ref


@pytest.mark.parametrize(
    "rel",
    [
        "skills/traigent-analyze-guidance/references/preflight.md",
        "skills/traigent-analyze-guidance/references/optimization-principles.md",
        "skills/traigent-analyze-results/SKILL.md",
    ],
)
def test_sweep_sites_name_agent_name(repo_root: Path, rel: str) -> None:
    assert "agent_name" in (repo_root / rel).read_text(encoding="utf-8")


def test_sdk_has_the_arguments_the_skills_teach(sdk_version_label: str) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.27.0"):
        pytest.skip("agent_name / run_title ship in SDK 0.27.0")
    import traigent

    params = inspect.signature(traigent.optimize).parameters
    for name in ("agent_name", "run_title", "run_description", "experiment_name"):
        assert name in params
    for name in ("tags", "metadata"):
        assert name not in params
