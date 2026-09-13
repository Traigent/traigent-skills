"""A verdict is relayed, never improved.

The three payloads here are the ones the live portal actually returned on the
dogfood run (2026-09-13): an abstain, an empty example-insights result, and a
decision brief at `low` confidence. Each is exactly the kind of result a relay
is tempted to round up into a pass, so each is pinned.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_tier2
from tier2_fake_backend import RUN_ID, FakeBackend


def approve(tier1: Path, backend: FakeBackend, check: str, *extra: str):
    return run_tier2(
        "--from-audit", str(tier1),
        "--backend-url", backend.url,
        "--run-id", RUN_ID,
        "--approve", check,
        *extra,
    )


def test_an_abstain_is_printed_as_an_abstain_and_said_not_to_be_a_pass(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = approve(healthy_tier1, backend, "evaluator-quality")
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "abstain" in out
    assert "This is not a pass" in out
    assert "no evaluator was assessed" in out
    # The two words a rounded-up relay would reach for.
    assert "reliable" not in out.lower()
    assert "passed" not in out.lower()


def test_the_empty_dataset_result_is_reported_with_both_numbers(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = approve(healthy_tier1, backend, "example-insights")
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "no example rows were returned" in out
    assert "`dataset_quality: 'low'`" in out
    assert "`example_count: 0`" in out


def test_a_low_confidence_stays_low(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend() as backend:
        completed = approve(healthy_tier1, backend, "decision-brief")
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "`confidence: 'low'`" in out
    assert "never upgraded here" in out


def test_a_forged_html_body_produces_no_verdict(
    healthy_tier1: Path, sentinel_key: str, tmp_path: Path
) -> None:
    receipt = tmp_path / "receipt.json"
    with FakeBackend(forge=True) as backend:
        completed = approve(healthy_tier1, backend, "evaluator-quality",
                            "--receipt", str(receipt))
    assert completed.returncode == 0, completed.stderr
    assert "unexpected payload" in completed.stdout
    assert "not the api you are looking for" not in completed.stdout
    rows = json.loads(receipt.read_text(encoding="utf-8"))["requests"]
    assert rows[0]["status"] == 200 and rows[0]["response_bytes"] > 0


def test_a_json_body_that_is_not_the_envelope_produces_no_verdict(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend(bad_envelope=True) as backend:
        completed = approve(healthy_tier1, backend, "evaluator-quality")
    assert completed.returncode == 0, completed.stderr
    assert "unexpected payload" in completed.stdout
    # The forged body says "excellent" and "reliable"; neither may be relayed.
    assert "excellent" not in completed.stdout
    assert "reliable" not in completed.stdout.lower()


def test_a_non_200_is_reported_as_a_status_not_as_a_body(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    with FakeBackend(error_status=500) as backend:
        completed = approve(healthy_tier1, backend, "evaluator-quality")
    assert completed.returncode == 0, completed.stderr
    assert "HTTP 500" in completed.stdout
    assert "upstream failure" not in completed.stdout


def test_the_relay_is_not_vacuous(
    healthy_tier1: Path, sentinel_key: str
) -> None:
    """Teeth: the same code path DOES print a payload when one is well-formed."""
    with FakeBackend() as backend:
        completed = approve(healthy_tier1, backend, "evaluator-quality")
    assert "the service returned, verbatim:" in completed.stdout
    assert "run_evaluator_quality.v1" in completed.stdout
