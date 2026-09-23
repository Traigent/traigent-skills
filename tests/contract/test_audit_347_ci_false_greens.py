"""Contract test: CI paths that used to report green without checking anything.

Each case below pins one fix: the scanner self-tests run in CI, the schema
vocabulary check cannot skip under CI, the released-SDK bucket loop fails when
its bucket list cannot be produced, and the runnable-snippet runner no longer
inherits the caller's shell.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from . import test_economics_reference
from .test_runnable_snippets import _offline_mock_env

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _jobs(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))["jobs"]


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [s for s in job["steps"] if s.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r}"
    return matches[0]


# --- A: scanner self-tests ---------------------------------------------------


def test_forensics_workflow_runs_the_scanner_self_tests() -> None:
    job = _jobs("forensics.yml")["repo-forensics"]
    run = _step(job, "Scanner self-tests")["run"]
    assert "pytest tests/repo_forensics tests/test_repo_forensics_ioc_manager.py" in run


# --- B: schema vocabulary --------------------------------------------------


def test_schema_vocabulary_check_fails_instead_of_skipping_under_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_economics_reference, "_schema_vocabulary_path", lambda: None)
    monkeypatch.setenv("CI", "true")
    try:
        with pytest.raises(pytest.fail.Exception, match="TRAIGENT_SCHEMA_REPO"):
            test_economics_reference._load_schema_vocabulary()
    except pytest.skip.Exception as exc:
        pytest.fail(f"a missing schema under CI skipped instead of failing: {exc}")
    monkeypatch.delenv("CI")
    with pytest.raises(pytest.skip.Exception):
        test_economics_reference._load_schema_vocabulary()


@pytest.mark.parametrize(
    ("workflow", "job", "step", "schema_path"),
    [
        ("contracts.yml", "released-contracts", "Run released SDK buckets", "_schema"),
        ("contracts.yml", "develop-contracts", "Run develop contract drift check", "_schema"),
        (
            "snapshot-refresh.yml",
            "generate-and-validate",
            "Validate refreshed contracts",
            "upstream/schema",
        ),
    ],
)
def test_every_ci_contract_run_has_the_public_schema(
    workflow: str, job: str, step: str, schema_path: str
) -> None:
    steps = _jobs(workflow)[job]["steps"]
    checkouts = [
        s
        for s in steps
        if s.get("with", {}).get("repository") == "Traigent/TraigentSchema"
    ]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["path"] == schema_path
    assert "token" not in checkouts[0]["with"]
    env = _step(_jobs(workflow)[job], step)["env"]
    assert env["TRAIGENT_SCHEMA_REPO"] == "${{ github.workspace }}/" + schema_path


# --- E: released-SDK bucket list -------------------------------------------


def _bucket_prelude() -> str:
    """The released-contracts step up to and including its empty-list guard."""
    run = _step(_jobs("contracts.yml")["released-contracts"], "Run released SDK buckets")["run"]
    assert "done < <(" not in run, "process substitution hides list_buckets.py failures"
    assert 'done <<< "$buckets"' in run
    head, sep, _ = run.partition("\nfi\n")
    assert sep, "empty-bucket guard not found"
    return head + sep


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize(
    ("fake_python", "succeeds"),
    [
        ("echo 'list_buckets crashed' >&2; exit 1", False),
        # A partial list followed by a crash must still fail: the empty-list
        # guard alone would let `|| true` through here.
        ("echo 0.21.3; exit 1", False),
        ("exit 0", False),
        ("echo 0.27.0", True),
    ],
)
def test_bucket_list_failure_fails_the_released_step(
    tmp_path: Path, fake_python: str, succeeds: bool
) -> None:
    fake = tmp_path / "python"
    fake.write_text(f"#!/usr/bin/env bash\n{fake_python}\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    result = subprocess.run(
        ["bash", "-c", _bucket_prelude()],
        env={"PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is succeeds, result.stdout + result.stderr


# --- F: runnable-snippet environment ---------------------------------------


def test_snippet_env_does_not_inherit_the_callers_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "TRAIGENT_MOCK_LLM": "true",
        "TRAIGENT_OFFLINE_MODE": "false",
        "TRAIGENT_BACKEND_URL": "https://example.invalid",
        "OPENAI_API_KEY": "sk-not-a-key",
        "CI": "true",
        "GITHUB_ACTIONS": "true",
    }.items():
        monkeypatch.setenv(name, value)
    env = _offline_mock_env()
    assert "TRAIGENT_MOCK_LLM" not in env
    assert "TRAIGENT_BACKEND_URL" not in env
    assert "OPENAI_API_KEY" not in env
    assert "CI" not in env and "GITHUB_ACTIONS" not in env
    assert env["TRAIGENT_OFFLINE_MODE"] == "true"
    assert env["PATH"] == os.environ["PATH"]
