"""The forensics gate must fail when it has nothing to scan.

Traigent/traigent-skills#504. ``run_forensics.sh`` resolved its target with
``realpath`` and never checked it: a missing or empty directory produced
"VERDICT: 0 findings" and exit 0, so a renamed ``skills/`` would keep the
zero-tolerance gate green while scanning nothing. The workflow also gets its own
``skills/*/SKILL.md`` count assertion before the scan.

This is a local fix to the vendored copy; re-copying ``tools/repo-forensics``
from upstream without it turns these tests red.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "repo-forensics" / "run_forensics.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "forensics.yml"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _run(target: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUNNER), str(target), "--skill-scan", "--format", "summary", *extra],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


@pytest.mark.parametrize(
    "make_target",
    [
        pytest.param(lambda tmp: tmp / "missing", id="missing-dir"),
        pytest.param(lambda tmp: tmp / "missing" / "deeper", id="missing-parent"),
        pytest.param(lambda tmp: tmp, id="empty-dir"),
        pytest.param(
            lambda tmp: (tmp / "only-dirs" / "nested").mkdir(parents=True) or tmp / "only-dirs",
            id="dirs-but-no-files",
        ),
    ],
)
def test_runner_refuses_a_target_with_nothing_to_scan(tmp_path: Path, make_target: Any) -> None:
    target = make_target(tmp_path)
    result = _run(target)
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "0 findings" not in output, output
    assert "scan incomplete" in output, output


def test_runner_refuses_a_file_target(tmp_path: Path) -> None:
    target = tmp_path / "SKILL.md"
    target.write_text("---\nname: demo\n---\n", encoding="utf-8")
    result = _run(target)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "not a directory" in result.stdout + result.stderr


def test_runner_still_scans_a_directory_with_files(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A harmless demo skill.\n---\n\n# Demo\n\nSay hello.\n",
        encoding="utf-8",
    )
    result = _run(tmp_path / "skills")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "EXIT CODE: 0 (clean)" in output, output


# --- workflow: skills/*/SKILL.md count assertion -------------------------------


def _guard_step() -> dict[str, Any]:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["repo-forensics"][
        "steps"
    ]
    names = [s.get("name") for s in steps]
    guard = "Assert the scan target holds skills"
    assert guard in names, names
    assert names.index(guard) < names.index(
        "Run repo-forensics (skill-scan, block on ANY finding)"
    ), "the skill-count guard must run before the scan"
    return steps[names.index(guard)]


def _run_guard(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-e", "-c", _guard_step()["run"]],
        env={"PATH": os.environ.get("PATH", ""), "GITHUB_WORKSPACE": str(workspace)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_workflow_guard_fails_without_skills(tmp_path: Path) -> None:
    assert _run_guard(tmp_path).returncode != 0
    (tmp_path / "skills" / "demo").mkdir(parents=True)
    assert _run_guard(tmp_path).returncode != 0, "a skill dir without SKILL.md must not pass"


def test_workflow_guard_passes_with_a_skill(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    result = _run_guard(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_workflow_guard_passes_on_this_repo() -> None:
    result = _run_guard(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


# --- leading-dash target --------------------------------------------------------


def test_runner_scans_a_target_whose_name_starts_with_a_dash(tmp_path: Path) -> None:
    # `realpath -foo` and `find -foo` read the name as an option; the runner must
    # still resolve and scan the directory instead of calling it empty.
    skill = tmp_path / "-skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A harmless demo skill.\n---\n\n# Demo\n\nSay hello.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(RUNNER), "-skills", "--skill-scan", "--format", "summary"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        cwd=tmp_path,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "EXIT CODE: 0 (clean)" in output, output


# --- runner: --reject-symlinks (opt-in symlink guard) ------------------------------------------


def _skill(root: Path, name: str = "demo") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    return skill


@pytest.mark.parametrize(
    "make_link",
    [
        pytest.param(
            lambda ws, outside: (ws / "skills" / "linked").symlink_to(outside, target_is_directory=True),
            id="symlinked-skill-dir",
        ),
        pytest.param(
            lambda ws, outside: (
                (ws / "skills" / "other").mkdir(),
                (ws / "skills" / "other" / "SKILL.md").symlink_to(outside / "SKILL.md"),
            ),
            id="symlinked-skill-md",
        ),
        pytest.param(
            lambda ws, outside: (ws / "skills" / "demo" / "notes.md").symlink_to(
                outside / "SKILL.md"
            ),
            id="symlinked-file-inside-a-skill",
        ),
    ],
)
def test_runner_rejects_a_symlink_under_the_target_when_asked(
    tmp_path: Path, make_link: Any
) -> None:
    # The scanners skip symlinks, so a symlinked skill would pass the
    # zero-tolerance gate without being read. The check lives in the runner (one
    # source of truth) so the documented local gate and CI behave the same.
    workspace = tmp_path / "ws"
    _skill(workspace / "skills")
    outside = _skill(tmp_path / "outside")
    clean = _run(workspace / "skills", "--reject-symlinks")
    assert clean.returncode == 0, "fixture must pass before the link: " + clean.stdout
    make_link(workspace, outside)
    result = _run(workspace / "skills", "--reject-symlinks")
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "symlinks are skipped by every scanner; scan would be vacuous for them" in output, output
    assert "0 findings" not in output, output


def test_runner_default_still_scans_a_tree_with_symlinks(tmp_path: Path) -> None:
    # The runner also vets untrusted third-party repos (--ci), where symlinks are
    # normal; rejecting them is opt-in so that use keeps working.
    workspace = tmp_path / "ws"
    skill = _skill(workspace / "skills")
    (skill / "notes.md").symlink_to(skill / "SKILL.md")
    result = _run(workspace / "skills")
    assert result.returncode == 0, result.stdout + result.stderr


def _scan_command_lines(workflow_text: str) -> str:
    steps = yaml.safe_load(workflow_text)["jobs"]["repo-forensics"]["steps"]
    scan = next(s for s in steps if s.get("name", "").startswith("Run repo-forensics"))
    return "\n".join(
        line for line in scan["run"].splitlines() if not line.lstrip().startswith("#")
    )


def test_workflow_scan_step_rejects_symlinks_via_the_runner() -> None:
    # Match the command line only: a comment mentioning the flag must not satisfy it.
    commands = _scan_command_lines(WORKFLOW.read_text(encoding="utf-8"))
    assert re.search(r"run_forensics\.sh[^\n]*--reject-symlinks", commands), commands


def test_workflow_pin_ignores_a_comment_that_names_the_flag() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--reject-symlinks --format summary" in text
    mutated = text.replace(" --reject-symlinks --format summary", " --format summary")
    assert "--reject-symlinks" in mutated, "comment must remain for this mutation to mean anything"
    assert not re.search(
        r"run_forensics\.sh[^\n]*--reject-symlinks", _scan_command_lines(mutated)
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_runner_fails_closed_when_find_cannot_read_a_subdirectory(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    skill = _skill(workspace / "skills")
    locked = skill / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        result = _run(workspace / "skills", "--reject-symlinks")
    finally:
        locked.chmod(0o755)
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "could not check for symlinks" in output, output
    assert str(locked) in output, output
