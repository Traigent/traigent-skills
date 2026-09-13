"""The two checks that shell out, asserted on argv rather than on behaviour.

The real `traigent` CLI is never spawned here: `traigent models` reaches a
provider and `traigent plan` reaches the portal. A recording stand-in first on
PATH is spawned instead, and what is pinned is the exact command line — every
flag of which exists on the installed SDK's own `--help` (the repo's
`tests/contract/test_env_and_cli.py` is what keeps that true).
"""

from __future__ import annotations

import json
from pathlib import Path

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
