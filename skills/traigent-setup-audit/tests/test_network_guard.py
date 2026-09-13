"""The zero-network claim is proved by running the guard, never by reading prose.

Three independent proofs:

1. the guard check has teeth — it reports ``inactive`` before the guard is
   installed and ``active`` after, in a fresh process;
2. a real socket call raises the guard's refusal once the guard is installed;
3. a scorer that opens a socket while scoring is reported as blocked, both
   through ``scorer_probe.py`` directly and through the whole audit.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _framed_result(stdout: str) -> dict:
    """The probe's own result line, found by its framing prefix.

    Reading the LAST line instead let a scorer's own output be read as the
    probe's result, so the marker is how the line is identified now.
    """
    audit = _load_audit_module()
    framed = [
        line[len(audit.RESULT_MARKER) :]
        for line in stdout.splitlines()
        if line.startswith(audit.RESULT_MARKER)
    ]
    assert len(framed) == 1, stdout
    return json.loads(framed[0])


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


GUARD_PROOF = """
import sys

sys.path.insert(0, {scripts!r})

import socket

import audit_project

print("before=" + audit_project.verify_network_guard())
audit_project.install_network_guard()
print("after=" + audit_project.verify_network_guard())

try:
    socket.create_connection(("localhost", 9))
except RuntimeError as exc:
    print("refusal=" + str(exc))
else:
    print("refusal=none")
"""


def test_guard_reports_inactive_before_install_and_active_after() -> None:
    """The guard check is a measurement, not a constant: it must be able to fail."""
    completed = subprocess.run(
        [sys.executable, "-c", GUARD_PROOF.format(scripts=str(SCRIPTS_DIR))],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert "before=inactive" in lines, completed.stdout
    assert "after=active" in lines, completed.stdout


def test_real_socket_call_raises_the_guard_refusal() -> None:
    audit = _load_audit_module()
    completed = subprocess.run(
        [sys.executable, "-c", GUARD_PROOF.format(scripts=str(SCRIPTS_DIR))],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert f"refusal={audit.GUARD_MESSAGE}" in completed.stdout.splitlines()


def test_scorer_probe_blocks_a_scorer_that_opens_a_socket() -> None:
    probe = SCRIPTS_DIR / "scorer_probe.py"
    request = {
        "module": str(FIXTURES / "netscorer" / "scorer.py"),
        "function": "score",
        "good": "a value",
        "partial": "a",
        "bad": "another value",
        "repeats": 3,
    }
    completed = subprocess.run(
        [sys.executable, str(probe), "--request-stdin"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = _framed_result(completed.stdout)
    assert result["network_guard"] == "active"
    assert result["network_blocked"] is True
    assert result["ran"] is False


def test_scorer_probe_runs_a_local_scorer_unharmed() -> None:
    """Teeth for the test above: the same probe path must still score normally."""
    probe = SCRIPTS_DIR / "scorer_probe.py"
    request = {
        "module": str(FIXTURES / "healthy" / "scorer.py"),
        "function": "score",
        "good": "a value",
        "partial": "a",
        "bad": "another value",
        "repeats": 3,
    }
    completed = subprocess.run(
        [sys.executable, str(probe), "--request-stdin"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = _framed_result(completed.stdout)
    assert result["ran"] is True
    assert result["network_guard"] == "active"
    assert result["scores"]["good"] == [1.0, 1.0, 1.0]
    assert result["scores"]["bad"] == [0.0]


def test_audit_reports_the_blocked_scorer_in_the_card(tmp_path: Path) -> None:
    audit = _load_audit_module()
    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "audit_project.py"),
            "--root",
            str(FIXTURES / "netscorer"),
            "--json",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["audit_process_guard"] == "active"
    assert report["scorer_probe"]["network_blocked"] is True
    assert report["areas"]["scorer"]["status"] == "attention"
    assert "network guard refused it" in completed.stdout
    assert audit.GUARD_MESSAGE.startswith("traigent-setup-audit:")
