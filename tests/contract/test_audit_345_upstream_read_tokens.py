"""Contract test: the snapshot workflows read private upstreams with short-lived,
single-repository App tokens, never with a long-lived repo secret.

The three workflows that compare the vendored backend-route and JS-API
snapshots against their upstreams went red for weeks once the long-lived token
they cloned with was rejected. They now mint a GitHub App installation token
per run, scoped to the one repository each clone reads. These checks pin that
shape, and execute each guard so a missing App credential still fails the run
instead of skipping to green.
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
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SNAPSHOT_WORKFLOWS = (
    "backend-snapshot-drift.yml",
    "js-api-drift.yml",
    "snapshot-refresh.yml",
)
PRIVATE_UPSTREAMS = {"TraigentBackend", "traigent-js"}
APP_TOKEN_ACTION = "actions/create-github-app-token@"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
ALLOWED_SECRETS = {"SKILLS_CI_READ_APP_PRIVATE_KEY"}


def _steps(name: str) -> list[dict[str, Any]]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.parametrize("name", SNAPSHOT_WORKFLOWS)
def test_only_the_app_private_key_secret_is_read(name: str) -> None:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert set(re.findall(r"secrets\.(\w+)", text)) == ALLOWED_SECRETS


@pytest.mark.parametrize("name", SNAPSHOT_WORKFLOWS)
def test_each_app_token_is_pinned_read_only_and_single_repository(name: str) -> None:
    minted = [s for s in _steps(name) if str(s.get("uses", "")).startswith(APP_TOKEN_ACTION)]
    assert minted, f"{name}: no App token is minted"
    for step in minted:
        assert PINNED.match(step["uses"]), f"{name}: {step['uses']} is not SHA-pinned"
        with_ = step["with"]
        assert with_["owner"] == "Traigent"
        assert with_["permission-contents"] == "read"
        assert with_["repositories"] in PRIVATE_UPSTREAMS, (
            f"{name}: a token must be scoped to exactly one private upstream, "
            f"got {with_['repositories']!r}"
        )


@pytest.mark.parametrize("name", SNAPSHOT_WORKFLOWS)
def test_upstream_reads_use_a_minted_token(name: str) -> None:
    for step in _steps(name):
        uses = str(step.get("uses", ""))
        if uses.startswith("actions/checkout@") and "token" in step.get("with", {}):
            assert re.fullmatch(
                r"\$\{\{ steps\.[\w-]+\.outputs\.token \}\}", step["with"]["token"]
            ), f"{name}: checkout token must come from a minted App token"
        for key, value in (step.get("env") or {}).items():
            if "TOKEN" in key and key != "GH_TOKEN":
                assert re.fullmatch(
                    r"\$\{\{ steps\.[\w-]+\.outputs\.token \}\}", value
                ), f"{name}: {key} must come from a minted App token"


def test_public_sdk_checkout_uses_no_token() -> None:
    checkouts = [
        s
        for s in _steps("snapshot-refresh.yml")
        if s.get("with", {}).get("repository") == "Traigent/Traigent"
    ]
    assert len(checkouts) == 1
    assert "token" not in checkouts[0]["with"]


def test_every_checkout_disables_persisted_credentials() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for step in _steps(path.name):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False, (
                    f"{path.name}: {step.get('name')} persists credentials"
                )


def _guard(name: str) -> dict[str, Any]:
    guards = [s for s in _steps(name) if str(s.get("name", "")).startswith("Guard")]
    assert len(guards) == 1, f"{name}: expected exactly one guard step"
    return guards[0]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize("name", SNAPSHOT_WORKFLOWS)
@pytest.mark.parametrize(
    ("client_id", "private_key", "armed"),
    [("", "", False), ("Iv1.x", "", False), ("", "key", False), ("Iv1.x", "key", True)],
)
def test_guard_fails_the_run_unless_both_app_credentials_exist(
    tmp_path: Path, name: str, client_id: str, private_key: str, armed: bool
) -> None:
    guard = _guard(name)
    assert set(guard["env"]) == {"APP_CLIENT_ID", "APP_PRIVATE_KEY"}
    output = tmp_path / "github_output"
    output.touch()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_OUTPUT": str(output),
        "APP_CLIENT_ID": client_id,
        "APP_PRIVATE_KEY": private_key,
    }
    result = subprocess.run(
        ["bash", "-e", "-c", guard["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if armed:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, f"{name}: guard passed without App credentials"
        assert "::error::" in result.stdout
        assert "armed=true" not in output.read_text()
