"""Public guidance contracts for cost accounting, helper discovery and editor confirmation."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from .test_audit_324_ci_gate_hygiene import _digest, _forbidden_in, _shipped_files

ROOT = Path(__file__).resolve().parents[2]


def _section(text: str, heading: str) -> str:
    return text.split(heading + "\n", 1)[1].split("\n## ", 1)[0]


def _helper_names(text: str) -> set[str]:
    return set(re.findall(r"`(traigent-[a-z-]+)`", text))


def test_readme_helper_inventory_matches_script_directories() -> None:
    readme = (ROOT / "README.md").read_text()
    actual = {
        path.parent.name
        for path in (ROOT / "skills").glob("*/scripts")
        if path.is_dir() and (path.parent / "SKILL.md").is_file()
    }
    inventory = readme.split("The following skills also ship Python helpers:", 1)[1].split("\n", 1)[0]
    requirements = _section(readme, "## Requirements").split("\n\n", 1)[0]
    assert actual
    assert _helper_names(inventory) == actual
    assert _helper_names(requirements) == actual
    assert "no model or network calls and no credential read" in inventory
    assert "no runtime" in requirements


def test_readme_recommendation_summary_agrees_with_canonical_policy() -> None:
    summary = _section((ROOT / "README.md").read_text(), "## Interaction policy")
    policy = (ROOT / "docs/shared/interaction-policy.v1.md").read_text()
    for concept in ("result-bearing step", "explicit decision point", "during setup or mid-walkthrough", "3", "one-line eligibility reason"):
        assert concept in summary
        assert concept in policy
    assert "end of each response" not in summary


@pytest.mark.parametrize("relative", ["docs/shared/run-cost-and-limits.v1.md", "skills/traigent-optimize-run/SKILL.md", "skills/traigent-optimize-run/references/execution-budget.md", "skills/traigent-eval-build/SKILL.md"])
def test_metric_judge_accounting_is_version_and_capture_scoped(relative: str) -> None:
    text = (ROOT / relative).read_text()
    for concept in ("0.28.0+", "0.27.x", "non-streaming LiteLLM", "synchronous LangChain", "usage and pricing", "cost-limit ledger", "evaluation_cost", "metric-key ceiling", "unintercepted provider-SDK/HTTP", "uncaptured streams", "pre-run estimator", "separate"):
        assert concept in text, (relative, concept)


@pytest.mark.parametrize("relative", ["docs/shared/run-cost-and-limits.v1.md", "skills/traigent-optimize-run/SKILL.md"])
def test_cost_budget_discloses_overshoot_and_approval(relative: str) -> None:
    text = (ROOT / relative).read_text()
    for concept in ("overshoot", "in-flight", "non-TTY", "TTY", "prior approval", "raise", "provider", "Advisory" if relative.endswith("SKILL.md") else "advisory", "guarantee", "TRAIGENT_COST_APPROVED"):
        assert concept in text, (relative, concept)
    assert "stops a run at the cap" not in text


@pytest.mark.parametrize("relative", ["docs/agent-setup/prompt.md", "skills/traigent-setup-quickstart/SKILL.md"])
def test_editor_opening_requires_human_confirmation(relative: str) -> None:
    text = (ROOT / relative).read_text()
    for concept in ("DISPLAY", "WAYLAND_DISPLAY", "SSH alone", "full-command searches", "invoking shell", "confirm the intended", "absolute path", "unsaved changes", "reload", "uncertain or fails", "open the printed absolute path manually", "open -t", "notepad"):
        assert concept in text, (relative, concept)
    assert "Verify the editor process is actually alive" not in text


def test_private_guard_includes_every_tracked_payload_and_doc() -> None:
    files = {path.relative_to(ROOT).as_posix() for path in _shipped_files()}
    assert "README.md" in files
    assert "docs/agent-setup/README.md" in files
    assert "skills/traigent-setup-quickstart/provenance.json" in files
    assert "skills/traigent-setup-audit/tests/tier2_fake_backend.py" in files
    assert not any(path.startswith(".github/") for path in files)


@pytest.mark.parametrize("location", ["README.md", "docs/note", "skills/new-skill/.metadata", "skills/new-skill/provenance.json"])
def test_private_guard_rejects_a_staged_payload_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, location: str) -> None:
    from . import test_audit_324_ci_gate_hygiene as guard

    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "_FORBIDDEN_DIGESTS", guard._FORBIDDEN_DIGESTS | {_digest("private-control-repository")})
    path = tmp_path / location
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("PRIVATE-CONTROL-REPOSITORY.\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "add", "--", location], cwd=tmp_path, check=True)
    with pytest.raises(AssertionError, match=re.escape(location)):
        guard.test_no_private_repository_or_internal_process_names_in_shipped_skill_files()


def test_choose_metric_judge_warning_has_the_same_capture_boundary() -> None:
    text = (ROOT / "skills/traigent-eval-choose-metric/SKILL.md").read_text()
    for concept in ("0.28.0+", "cost-limit ledger", "unintercepted provider-SDK/HTTP", "pre-run estimator", "evaluation_cost"):
        assert concept in text
    assert "does not see judge calls made inside a metric function" not in text


@pytest.mark.parametrize("suffix", ["coding-agents", "spine"])
def test_removed_plugin_identifiers_cannot_return(suffix: str) -> None:
    private_identifier = "-".join(("traigent", suffix))
    assert _forbidden_in(private_identifier) == [private_identifier]
