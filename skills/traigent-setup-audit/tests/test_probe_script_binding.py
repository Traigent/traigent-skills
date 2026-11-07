"""Running the audit from under /tmp must not hide the probe script.

bwrap mounts a tmpfs on /tmp; a copy of the skill living there lost
`scorer_probe.py` inside the sandbox, the probe printed nothing, and the card
blamed the scorer. The script's directory is now bound back in, and the message
for "no readable result" no longer assigns a cause.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
audit = importlib.import_module("audit_project")


def test_the_probe_script_directory_is_bound_into_the_sandbox() -> None:
    if audit.detect_isolation()[1] != "bwrap":
        pytest.skip("bwrap is not the active backend on this machine")
    _, backend, args, terminator = audit.detect_isolation()
    command = audit.isolation_command(
        backend, args, terminator, [audit.PROBE_SCRIPT.parent]
    )
    script_dir = str(audit.PROBE_SCRIPT.parent.resolve())
    assert command[command.index("--tmpfs") :].count(script_dir) == 2


def test_a_copy_of_the_skill_under_tmp_still_probes(tmp_path: Path) -> None:
    if audit.detect_isolation()[1] != "bwrap":
        pytest.skip("bwrap is not the active backend on this machine")
    if not str(tmp_path.resolve()).startswith("/tmp"):
        pytest.skip("pytest's tmp_path is not under /tmp here")
    scripts = tmp_path / "skill" / "scripts"
    shutil.copytree(SKILL_DIR / "scripts", scripts)
    project = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", project)
    out = tmp_path / "report.json"
    completed = subprocess.run(
        [sys.executable, str(scripts / "audit_project.py"), "--root", str(project),
         "--json", str(out)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    probe = json.loads(out.read_text(encoding="utf-8"))["scorer_probe"]
    assert probe["ran"] is True, probe


def test_no_readable_result_does_not_blame_the_scorer() -> None:
    sentence = audit.PROBE_FAILURE_SENTENCE["no-result"]
    assert "ended the process" not in sentence
    assert "most likely" not in sentence
    assert "probe diagnostics" in sentence
