"""The key value must not reach a card, a receipt, a stream, or an error.

Tier 1 learned this the expensive way: an exception message and a subprocess's
stderr were each observed carrying an API key. Tier 2 adds a path Tier 1 never
had — the key is now actually SENT — so the sentinel is checked on every output
the script can produce, including the one case where the SERVER echoes the key
back in its own error body.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import recorded_argv, run_tier2
from tier2_fake_backend import RUN_ID, FakeBackend


def all_output(completed, *paths: Path) -> str:
    text = completed.stdout + completed.stderr
    for path in paths:
        if path.exists():
            text += path.read_text(encoding="utf-8")
    return text


def test_the_key_is_absent_from_the_offer(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    completed = run_tier2("--from-audit", str(healthy_tier1), "--list-runs")
    assert completed.returncode == 0, completed.stderr
    assert sentinel_key not in all_output(completed)
    # The NAME is reported, so the user knows a key is configured.
    assert "`TRAIGENT_API_KEY` is set" in completed.stdout


def test_the_key_is_absent_from_every_run_mode_output(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    record = tmp_path / "record.json"
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
            "--approve", "example-insights",
            "--approve", "example-scoring",
            "--approve", "decision-brief",
            "--receipt", str(receipt),
            "--json", str(record),
        )
    assert completed.returncode == 0, completed.stderr
    assert sentinel_key not in all_output(completed, receipt, record)
    assert receipt.exists() and record.exists()


def test_a_server_that_echoes_the_key_back_is_not_relayed(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    with FakeBackend(error_status=500, echo_key_in_error=True) as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
            "--receipt", str(receipt),
        )
    assert completed.returncode == 0, completed.stderr
    assert sentinel_key not in all_output(completed, receipt)
    assert "HTTP 500" in completed.stdout


def test_the_sentinel_check_is_not_vacuous(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    """Teeth: the key really is in this process's environment and really is sent."""
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 0, completed.stderr
        assert backend.log and backend.log[0]["has_api_key"]


def test_no_key_reaches_a_command_line(
    healthy_tier1: Path, sentinel_key: str, fake_traigent_cli: Path, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    completed = run_tier2(
        "--from-audit", str(healthy_tier1),
        "--approve", "model-ids",
        "--receipt", str(receipt),
    )
    assert completed.returncode == 0, completed.stderr
    calls = recorded_argv(fake_traigent_cli)
    assert calls, "the model-ids check spawned nothing"
    for argv in calls:
        assert sentinel_key not in " ".join(argv)
    spawned = json.loads(receipt.read_text(encoding="utf-8"))["subprocesses"]
    assert sentinel_key not in json.dumps(spawned)
