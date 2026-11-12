"""refresh_backend_routes.py must not default to one developer's checkout.

Traigent/traigent-skills#505. ``--repo`` defaulted to an absolute path under a
developer's home directory; without it the script ran ``git -C <that path>`` and
died with a raw ``CalledProcessError`` traceback that never mentioned
``--repo``. Now the checkout comes from ``--repo`` or ``$TRAIGENT_BACKEND_REPO``,
and a missing or unusable checkout is a one-line actionable error.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "contract" / "refresh_backend_routes.py"


def _run(
    tmp_path: Path, *args: str, backend_env: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    if backend_env is not None:
        env["TRAIGENT_BACKEND_REPO"] = backend_env
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--out", str(tmp_path / "out.json"), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_source_has_no_developer_home_default() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "/home/" not in source and "/Users/" not in source


def test_without_repo_it_says_how_to_pass_one(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert "--repo" in result.stderr and "TRAIGENT_BACKEND_REPO" in result.stderr
    assert not (tmp_path / "out.json").exists()


def test_a_non_git_repo_is_an_actionable_error(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    for result in (
        _run(tmp_path, "--repo", str(not_a_repo)),
        _run(tmp_path, backend_env=str(not_a_repo)),
    ):
        assert result.returncode == 1, result.stderr
        assert "Traceback" not in result.stderr, result.stderr
        assert str(not_a_repo) in result.stderr
        assert "TraigentBackend" in result.stderr


def test_a_missing_ref_is_an_actionable_error(tmp_path: Path) -> None:
    repo = tmp_path / "backend"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    result = _run(tmp_path, "--repo", str(repo), "--ref", "origin/develop")
    assert result.returncode == 1, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert "origin/develop" in result.stderr and "--ref" in result.stderr
