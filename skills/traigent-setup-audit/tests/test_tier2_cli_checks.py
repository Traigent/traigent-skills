"""The two checks that shell out, asserted on argv rather than on behaviour.

The real `traigent` CLI is never spawned here: `traigent models` reaches a
provider and `traigent plan` reaches the portal. A recording stand-in first on
PATH is spawned instead, and what is pinned is the exact command line — every
flag of which exists on the installed SDK's own `--help` (the repo's
`tests/contract/test_env_and_cli.py` is what keeps that true).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import tier2_checks
from conftest import recorded_argv, run_tier2
from tier2_fake_backend import FakeBackend


def test_model_ids_calls_the_cli_once_per_declared_id(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--approve", "model-ids",
    )
    assert completed.returncode == 0, completed.stderr
    assert recorded_argv(fake_traigent_cli) == [
        ["models", "--provider", "anthropic", "--check",
         "claude-haiku-4-5-20251001", "--json"],
        ["models", "--provider", "openai", "--check", "gpt-4o-mini", "--json"],
    ]


def test_a_model_id_with_no_inferable_provider_is_skipped_not_guessed(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path, tmp_path: Path
) -> None:
    report = json.loads(healthy_tier1.read_text(encoding="utf-8"))
    report["setup"]["model_ids_declared"] = ["llama-3-70b-instruct"]
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(report), encoding="utf-8")

    completed = run_tier2("--from-audit", str(edited), "--approve", "model-ids")
    assert completed.returncode == 0, completed.stderr
    assert recorded_argv(fake_traigent_cli) == []
    assert "no provider can be inferred" in completed.stdout


def test_plan_sends_the_tier_1_numbers_and_the_users_own_cap(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--backend-url", "https://portal.traigent.ai",
        "--approve", "plan",
        "--cost-limit", "5",
        "--max-trials", "6",
        "--task", "answer support questions",
    )
    assert completed.returncode == 0, completed.stderr
    assert recorded_argv(fake_traigent_cli) == [
        [
            "plan",
            "--backend-url", "https://portal.traigent.ai",
            "--task-description", "answer support questions",
            "--dataset-size", "70",
            "--has-holdout",
            "--objective", "accuracy",
            "--max-trials", "6",
            "--cost-limit", "5.0",
            "--json",
        ]
    ]
    assert "is not a budget the service authored" in completed.stdout


def test_plan_without_a_cost_limit_exits_2_and_spawns_nothing(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1), "--approve", "plan")
    assert completed.returncode == 2
    assert recorded_argv(fake_traigent_cli) == []
    assert "the cap is yours to set" in completed.stderr


def test_a_cli_check_never_reaches_the_backend(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    """`model-ids` is provider egress, not Traigent egress: no request is made."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--approve", "model-ids",
        )
        assert completed.returncode == 0, completed.stderr
        assert backend.log == []
    assert recorded_argv(fake_traigent_cli)


def test_the_plan_relay_shows_evidence_level_objectives_and_the_advisory_warning(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    """What the plan actually returned on the dogfood run, relayed as returned.

    `evidence_level: low`, the caller's own cap echoed back, a command that had
    been retired from the SDK, and the cost objective oriented to maximize. The
    user has to be able to SEE the orientation, so it is printed.
    """
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--backend-url", "https://portal.traigent.ai",
        "--approve", "plan",
        "--cost-limit", "5",
    )
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "`evidence_level: 'low'`, relayed verbatim." in out
    assert "`objectives`, as returned" in out
    assert '"orientation": "maximize"' in out
    assert "is not a budget the service authored" in out
    assert "check any command against `--help` before running it" in out


def test_model_ids_with_no_traigent_on_path_is_refused_before_any_process(
    healthy_tier1: Path, tmp_path: Path, monkeypatch
) -> None:
    """A CLI check that cannot spawn did not run, so it is not exit 0.

    Exit 0 means "the approved checks ran". A missing CLI used to print "cannot
    run" into the run record, write a receipt and exit 0 — which a wrapper
    branching on the exit code reads as done.
    """
    original_path = os.getenv("PATH", "")
    empty = tmp_path / "empty"
    empty.mkdir()
    receipt = tmp_path / "r.json"
    record = tmp_path / "rec.json"
    approval = ("--from-audit", str(healthy_tier1), "--approve", "model-ids",
                "--receipt", str(receipt), "--json", str(record))

    monkeypatch.setenv("PATH", str(empty))
    completed = run_tier2(*approval)
    assert completed.returncode == 2, completed.stdout
    assert "`traigent` is not on PATH" in completed.stderr
    assert "`model-ids`" in completed.stderr
    assert not receipt.exists()
    assert not record.exists()
    assert "cannot run" not in completed.stdout

    # Control: a CLI that is on PATH and fails still ran, so that is exit 0
    # with a receipt.
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    stub = stub_dir / "traigent"
    stub.write_text(f"#!{sys.executable}\nraise SystemExit(1)\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{original_path}")
    failing = run_tier2(*approval)
    assert failing.returncode == 0, failing.stderr
    assert receipt.exists()


def test_plan_with_no_traigent_on_path_is_refused_before_any_process(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Every approved CLI check is named, and nothing runs, not even model-ids.

    In process, with the SDK's User-Agent stubbed, so the refusal under test is
    the missing CLI and not the missing distribution.
    """
    monkeypatch.setattr(tier2_checks, "sdk_user_agent", lambda: "traigent/0.30.0")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    receipt = tmp_path / "r.json"

    code = tier2_checks.main([
        "--from-audit", str(healthy_tier1),
        "--approve", "plan",
        "--approve", "model-ids",
        "--cost-limit", "1",
        "--receipt", str(receipt),
    ])
    captured = capsys.readouterr()
    assert code == 2, captured.out
    assert "`model-ids`" in captured.err
    assert "`plan`" in captured.err
    assert not receipt.exists()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-5"])
def test_a_cap_that_is_not_a_finite_positive_number_is_a_usage_error(
    healthy_tier1: Path, value: str
) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1), f"--cost-limit={value}")
    assert completed.returncode == 2, completed.stdout
    assert "--cost-limit" in completed.stderr
    assert "is not a finite number above zero" in completed.stderr
    assert "APPROVAL CARD" not in completed.stdout

    # Control: a usable cap is accepted, and plan is still the recommendation.
    usable = run_tier2("--from-audit", str(healthy_tier1), "--cost-limit=1.0")
    assert usable.returncode == 0, usable.stderr
    assert "APPROVAL CARD — plan   (recommended)" in usable.stdout


def test_run_mode_refuses_a_bad_cap_before_spawning(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path
) -> None:
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--approve", "plan",
        "--cost-limit=nan",
    )
    assert completed.returncode == 2, completed.stdout
    assert "--cost-limit" in completed.stderr
    assert recorded_argv(fake_traigent_cli) == []


@pytest.mark.parametrize("arg", [
    "--timeout=nan", "--timeout=-1", "--timeout=0",
    "--max-trials=0", "--max-trials=-1",
])
def test_timeout_and_max_trials_must_be_usable(healthy_tier1: Path, arg: str) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1), arg)
    assert completed.returncode == 2, completed.stdout
    assert arg.split("=", 1)[0] in completed.stderr
