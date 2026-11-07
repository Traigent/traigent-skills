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


def test_the_bwrap_variants_mask_host_sockets_and_keep_the_rebinds_after() -> None:
    bwrap = [entry for entry in audit.ISOLATION_BACKENDS if entry[0] == "bwrap"]
    assert len(bwrap) >= 2
    widest = bwrap[0][1]
    assert widest.count("--tmpfs") == 3 and "/run" in widest and "/var/run" in widest
    assert "--unshare-ipc" in widest and "--unshare-pid" in widest
    # The plain argv stays as the last bwrap fallback.
    assert "/run" not in bwrap[-1][1]
    command = audit.isolation_command("bwrap", widest, ["--"], [Path(__file__).parent])
    here = str(Path(__file__).parent.resolve())
    assert command.index(here) > max(
        i for i, token in enumerate(command) if token == "--tmpfs"
    )


def test_the_note_names_only_what_the_selected_variant_did() -> None:
    bwrap = [entry[1] for entry in audit.ISOLATION_BACKENDS if entry[0] == "bwrap"]
    widest, plain = bwrap[0], bwrap[-1]
    full = audit.guard_note("isolated (bwrap)", widest)
    assert "/run" in full and "IPC" in full and "PID" in full
    fallback = audit.guard_note("isolated (bwrap)", plain)
    assert "/run" not in fallback and "IPC" not in fallback and "PID" not in fallback
    assert "read-only" in fallback and "not a security boundary" in fallback
    for note in (full, fallback):
        for banned in ("cannot write", "reach nothing"):
            assert banned not in note


def test_the_note_follows_the_final_command_and_its_later_binds() -> None:
    widest = [e[1] for e in audit.ISOLATION_BACKENDS if e[0] == "bwrap"][0]
    plain = [e[1] for e in audit.ISOLATION_BACKENDS if e[0] == "bwrap"][-1]
    under_run = [*widest, "--ro-bind", "/run/user/1/proj", "/run/user/1/proj", "--"]
    note = audit.guard_note("isolated (bwrap)", widest, under_run)
    assert "masked except the re-bound project directories" in note
    elsewhere = [*widest, "--ro-bind", "/srv/proj", "/srv/proj", "--"]
    note = audit.guard_note("isolated (bwrap)", widest, elsewhere)
    assert "/run" in note and "except" not in note
    var_run = [*widest, "--ro-bind", "/var/run/x", "/var/run/x"]
    assert "except" in audit.guard_note("isolated (bwrap)", widest, var_run)
    # The plain variant never claimed a mask, whatever it binds.
    plain_cmd = [*plain, "--ro-bind", "/run/x", "/run/x"]
    assert "/run" not in audit.guard_note("isolated (bwrap)", plain, plain_cmd)


def _bwrap_variants() -> tuple[list[str], list[str]]:
    bwrap = [e[1] for e in audit.ISOLATION_BACKENDS if e[0] == "bwrap"]
    return bwrap[0], bwrap[-1]


def test_run_is_masked_only_on_the_adjacent_tmpfs_pair() -> None:
    widest, plain = _bwrap_variants()
    plain_cmd = [*plain, "--ro-bind", "/run", "/run", "--"]
    assert "/run" not in audit.guard_note("isolated (bwrap)", plain, plain_cmd)
    full_cmd = [*widest, "--ro-bind", "/run", "/run", "--"]
    note = audit.guard_note("isolated (bwrap)", widest, full_cmd)
    assert "masked except the re-bound project directories" in note
    bound = [*widest, "--bind", "/var/run/x", "/var/run/x"]
    assert "except" in audit.guard_note("isolated (bwrap)", widest, bound)


def test_no_probe_means_no_ran_claim() -> None:
    widest, _ = _bwrap_variants()
    first = audit.not_established("isolated (bwrap)", widest, None, probe_ran=False)[0]
    assert "No scorer was probed" in first and "ran with" not in first
    ran = audit.not_established("isolated (bwrap)", widest, None, probe_ran=True)[0]
    assert ran.startswith("The probe subprocess ran with")
