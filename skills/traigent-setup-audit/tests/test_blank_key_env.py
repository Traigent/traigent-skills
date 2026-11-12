"""A key variable exported empty (or whitespace only) is not a set key.

`export OPENAI_API_KEY=` in a template, or a CI secret that did not resolve,
leaves the name in the environment with no usable value. Reporting it as "set"
hides the missing-key signal in the Setup area and in the Tier 2 offer.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, run_tier2
from tier2_fake_backend import RUN_ID, FakeBackend

import audit_project as audit

BLANKS = ["", "   ", "\t\n"]


@pytest.mark.parametrize("blank", BLANKS)
def test_a_blank_key_variable_is_not_reported_as_set(
    tmp_path: Path, monkeypatch, blank: str
) -> None:
    for name in audit.KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", blank)
    monkeypatch.setenv("TRAIGENT_API_KEY", blank)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-value")

    keys = audit.key_presence(tmp_path, [])

    assert keys["names_set_in_environment"] == ["ANTHROPIC_API_KEY"]


def test_the_audit_report_says_none_set_when_every_key_is_blank(
    tmp_path: Path, monkeypatch
) -> None:
    for name in audit.KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("TRAIGENT_API_KEY", "  ")
    completed = subprocess.run(
        [sys.executable, "-I", str(SCRIPTS_DIR / "audit_project.py"),
         "--root", str(tmp_path)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "set in this environment:" not in completed.stdout
    assert "found none set" in completed.stdout


@pytest.mark.parametrize("blank", BLANKS)
def test_the_tier2_offer_says_not_set_for_a_blank_traigent_key(
    healthy_tier1: Path, monkeypatch, blank: str
) -> None:
    monkeypatch.setenv("TRAIGENT_API_KEY", blank)
    completed = run_tier2("--from-audit", str(healthy_tier1))
    assert completed.returncode == 0, completed.stderr
    assert "`TRAIGENT_API_KEY` is NOT set." in completed.stdout


@pytest.mark.parametrize("blank", BLANKS)
def test_an_approved_check_refuses_a_blank_traigent_key_before_any_request(
    healthy_tier1: Path, monkeypatch, blank: str
) -> None:
    # The offer says NOT set for a blank key; the approved run must agree and
    # refuse instead of sending a blank credential to the backend.
    monkeypatch.setenv("TRAIGENT_API_KEY", blank)
    with FakeBackend() as backend:
        completed = run_tier2(
            "--from-audit", str(healthy_tier1),
            "--backend-url", backend.url,
            "--run-id", RUN_ID,
            "--approve", "evaluator-quality",
        )
        assert completed.returncode == 2, completed.stderr
        assert backend.log == []
        assert "TRAIGENT_API_KEY is not set" in completed.stderr


def test_the_key_evidence_strings_do_not_claim_no_value_is_read() -> None:
    # Both scripts now look at the value (blank or not), so "reads no value" /
    # "never read" would be false; what stays true is never printed or stored.
    for script in ("audit_project.py", "tier2_checks.py"):
        text = (SCRIPTS_DIR / script).read_text(encoding="utf-8")
        assert "the audit reads no value" not in text, script
        assert "the value is never read here" not in text, script
