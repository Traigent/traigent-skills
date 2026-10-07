"""Execute the documented adjacent-ignore rule before any key is written."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

QUICKSTART = "skills/traigent-setup-quickstart/SKILL.md"
REFERENCES = (
    "skills/traigent-setup-quickstart/references/environment-variables.md",
    "skills/traigent-setup-quickstart/references/first-value-fallback.md",
)
SENTINEL = "env-content-must-not-be-printed"


def documented_block(repo_root: Path) -> str:
    text = (repo_root / QUICKSTART).read_text(encoding="utf-8")
    section = text.split("### Using a .env File\n", 1)[1].split("#### ", 1)[0]
    blocks = re.findall(r"^```bash\n(.*?)^```", section, re.M | re.S)
    assert len(blocks) == 1, "the .env write rule must have one executable home"
    return blocks[0]


def git(project: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=project, env=env, capture_output=True, text=True, check=False,
    )


@pytest.fixture
def shell_env(tmp_path: Path) -> dict[str, str]:
    # The rule deliberately stops on any ancestor `.git`, so the scratch tree must have none.
    for parent in tmp_path.parents:
        if (parent / ".git").exists():
            pytest.skip(f"stray {parent / '.git'} above the scratch dir; use --basetemp elsewhere")
    assert shutil.which("git") and shutil.which("bash"), "git and bash must be installed"
    home = tmp_path / "home"
    home.mkdir()
    return {
        "PATH": os.environ.get("PATH", ""), "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    }


@pytest.mark.parametrize("strict", [False, True], ids=["plain-shell", "strict-shell"])
@pytest.mark.parametrize(
    "scenario",
    ["not-repo", "repo-no-ignore", "repo-ignore", "existing-env",
     "tracked-env", "earlier-negation", "no-final-newline", "nested-repo", "git-ceiling"],
)
def test_documented_rule_protects_env(
    repo_root: Path, tmp_path: Path, shell_env: dict[str, str], scenario: str, strict: bool,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    if scenario != "not-repo":
        assert git(project, shell_env, "init").returncode == 0
    if scenario == "nested-repo":
        project = project / "nested"
        project.mkdir()
        assert git(project, shell_env, "init").returncode == 0
    if scenario in {"repo-ignore", "existing-env"}:
        (project / ".gitignore").write_text("build/\n.env\n", encoding="utf-8")
    elif scenario == "earlier-negation":
        (project / ".gitignore").write_text(".env\n!.env\n", encoding="utf-8")
    elif scenario == "no-final-newline":
        (project / ".gitignore").write_text("build/", encoding="utf-8")
    if scenario in {"existing-env", "tracked-env"}:
        (project / ".env").write_text(SENTINEL, encoding="utf-8")
        (project / ".env").chmod(0o644)
    if scenario == "tracked-env":
        assert git(project, shell_env, "add", ".env").returncode == 0
    if scenario == "git-ceiling":
        project = project / "below-ceiling"
        project.mkdir()
        shell_env["GIT_CEILING_DIRECTORIES"] = str(project.parent)
    block = documented_block(repo_root)
    command = ("set -euo pipefail\n" if strict else "") + block
    done = subprocess.run(
        ["bash", "-c", command], cwd=project, env=shell_env,
        capture_output=True, text=True, check=False,
    )
    assert SENTINEL not in done.stdout + done.stderr
    if scenario == "tracked-env":
        assert done.returncode != 0
        assert "git rm --cached .env" in done.stderr
        assert (project / ".env").read_text() == SENTINEL
        assert not (project / ".gitignore").exists()
        return
    assert done.returncode == 0, done.stderr
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600
    if scenario == "existing-env":
        assert (project / ".env").read_text() == SENTINEL
    ignore = (project / ".gitignore").read_text()
    assert ignore.splitlines()[-1] == ".env"
    # The rule must be idempotent; rerunning preserves both files.
    before = (project / ".env").read_bytes()
    again = subprocess.run(
        ["bash", "-c", command], cwd=project, env=shell_env,
        capture_output=True, text=True, check=False,
    )
    assert again.returncode == 0, again.stderr
    assert (project / ".gitignore").read_text() == ignore
    assert (project / ".env").read_bytes() == before
    # Check Git itself, including when Git is initialized only after the block.
    shell_env.pop("GIT_CEILING_DIRECTORIES", None)
    if scenario == "not-repo":
        assert git(project, shell_env, "init").returncode == 0
    assert git(project, shell_env, "check-ignore", "-q", "--", ".env").returncode == 0
    (project / ".env").write_text(SENTINEL, encoding="utf-8")
    assert git(project, shell_env, "add", ".").returncode == 0
    assert git(project, shell_env, "ls-files", "--error-unmatch", "--", ".env").returncode == 1


def run_block(repo_root, project, env):
    return subprocess.run(
        [shutil.which("bash"), "-c", documented_block(repo_root)], cwd=project, env=env,
        capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("failure", ["git-exits-128", "git-missing", "corrupt-git-dir", "dubious"])
def test_rule_stops_on_unexpected_git_errors(
    repo_root: Path, tmp_path: Path, shell_env: dict[str, str], failure: str,
) -> None:
    """A git failure must never be read as "not tracked": no key-entry, nothing written."""
    project = tmp_path / "project"
    project.mkdir()
    env = dict(shell_env)
    if failure == "git-exits-128":
        assert git(project, shell_env, "init").returncode == 0
        fake = tmp_path / "fakebin"
        fake.mkdir()
        (fake / "git").write_text(
            "#!/bin/sh\necho 'fatal: detected dubious ownership in repository' >&2\nexit 128\n")
        (fake / "git").chmod(0o755)
        env["PATH"] = f"{fake}:{env['PATH']}"
    elif failure == "dubious":
        assert git(project, shell_env, "init").returncode == 0
        fake = tmp_path / "fakebin"
        fake.mkdir()
        (fake / "git").write_text("#!/bin/sh\nexit 128\n")
        (fake / "git").chmod(0o755)
        env["PATH"] = f"{fake}:{env['PATH']}"
    elif failure == "git-missing":
        assert git(project, shell_env, "init").returncode == 0
        bindir = tmp_path / "nogit"
        bindir.mkdir()
        for tool in ("tail", "printf", "touch", "chmod", "dirname", "cat"):
            found = shutil.which(tool)
            if found:
                (bindir / tool).symlink_to(found)
        env["PATH"] = str(bindir)
    else:  # a .git that is not a valid repository
        (project / ".git").mkdir()
        (project / ".git" / "HEAD").write_text("garbage\n")
    (project / ".env").write_text(SENTINEL, encoding="utf-8")
    done = run_block(repo_root, project, env)
    assert done.returncode != 0, done.stderr
    assert "STOP" in done.stderr
    assert SENTINEL not in done.stdout + done.stderr
    assert (project / ".env").read_text() == SENTINEL
    assert not (project / ".gitignore").exists()


@pytest.mark.parametrize("strict", [False, True], ids=["plain-shell", "strict-shell"])
@pytest.mark.parametrize("var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"])
@pytest.mark.parametrize("target", ["missing", "corrupt"])
def test_rule_stops_on_unusable_external_git_env(
    repo_root: Path, tmp_path: Path, shell_env: dict[str, str], var: str, target: str, strict: bool,
) -> None:
    """An unusable external GIT_* location reads as "not a git repository"; it must still stop."""
    project = tmp_path / "project"
    project.mkdir()
    bogus = tmp_path / "bogus"
    if target == "corrupt":
        bogus.mkdir()
        (bogus / "HEAD").write_text("garbage\n")
    (project / ".env").write_text(SENTINEL, encoding="utf-8")
    env = {**shell_env, var: str(bogus)}
    block = documented_block(repo_root)
    done = subprocess.run(
        [shutil.which("bash"), "-c", ("set -euo pipefail\n" if strict else "") + block],
        cwd=project, env=env, capture_output=True, text=True, check=False,
    )
    assert done.returncode != 0, done.stderr
    assert "STOP" in done.stderr
    assert SENTINEL not in done.stdout + done.stderr
    assert (project / ".env").read_text() == SENTINEL
    assert not (project / ".gitignore").exists()


def test_rule_proceeds_without_git_outside_any_repo(
    repo_root: Path, tmp_path: Path, shell_env: dict[str, str],
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    bindir = tmp_path / "nogit"
    bindir.mkdir()
    for tool in ("tail", "printf", "touch", "chmod", "dirname"):
        (bindir / tool).symlink_to(shutil.which(tool))
    env = {**shell_env, "PATH": str(bindir)}
    done = run_block(repo_root, project, env)
    assert done.returncode == 0, done.stderr
    assert (project / ".gitignore").read_text().splitlines()[-1] == ".env"


@pytest.mark.parametrize("name", [".env", ".gitignore"])
@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_rule_refuses_non_plain_paths(
    repo_root: Path, tmp_path: Path, shell_env: dict[str, str], name: str, kind: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text(SENTINEL, encoding="utf-8")
        (project / name).symlink_to(target)
    else:
        (project / name).mkdir()
    done = subprocess.run(
        ["bash", "-c", documented_block(repo_root)], cwd=project, env=shell_env,
        capture_output=True, text=True, check=False,
    )
    assert done.returncode != 0
    assert "must be a plain file" in done.stderr
    assert SENTINEL not in done.stdout + done.stderr
    if kind == "symlink":
        assert target.read_text() == SENTINEL


@pytest.mark.parametrize("path", (QUICKSTART, *REFERENCES))
def test_docs_do_not_teach_literal_key_exports(repo_root: Path, path: str) -> None:
    text = (repo_root / path).read_text(encoding="utf-8")
    exports = re.findall(
        r"^\s*(?:>\s*)?export\s+[A-Z_]*(?:KEY|TOKEN|PASSWORD)\s*=\s*([^\n]+)", text, re.M,
    )
    assert all(value.lstrip('"\'').startswith("$") for value in exports), path


def test_reference_points_to_the_one_home(repo_root: Path) -> None:
    text = (repo_root / REFERENCES[0]).read_text(encoding="utf-8")
    assert "../SKILL.md#using-a-env-file" in text
    assert "git ls-files --error-unmatch" not in text
    assert "check_env_file.py" not in text
