"""The probe runs in its own process group under resource caps.

`subprocess.run(timeout=)` kills only the direct child, so a scorer that forked
a helper left it running after the audit reported a timeout. These tests start
a real process tree and look for survivors.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
audit = importlib.import_module("audit_project")

posix_only = pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX")

FORKER = (
    "import os, sys, time\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    time.sleep(60)\n"
    "    os._exit(0)\n"
    "open(sys.argv[1], 'w').write(str(pid))\n"
    "sys.stdout.flush()\n"
    "time.sleep(60)\n"
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A killed child that nobody reaped is a zombie: dead for our purposes.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


@posix_only
def test_a_timeout_leaves_no_surviving_child(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "PROBE_TIMEOUT_SECONDS", 1)
    pid_file = tmp_path / "child.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        audit._run_probe_process([sys.executable, "-c", FORKER, str(pid_file)], "")
    child = int(pid_file.read_text())
    assert _wait_gone(child), f"forked child {child} survived the probe timeout"


@posix_only
def test_a_child_left_behind_by_a_normal_exit_is_swept(tmp_path: Path) -> None:
    code = (
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    os.close(1)\n"  # let the pipes reach EOF so only the sweep can kill it
        "    os.close(2)\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "open(sys.argv[1], 'w').write(str(pid))\n"
    )
    pid_file = tmp_path / "child.pid"
    done = audit._run_probe_process([sys.executable, "-c", code, str(pid_file)], "")
    assert done.returncode == 0
    assert _wait_gone(int(pid_file.read_text()))


@posix_only
def test_the_probe_runs_in_its_own_session(tmp_path: Path) -> None:
    code = "import os; print(os.getsid(0) == os.getpid())"
    done = audit._run_probe_process([sys.executable, "-c", code], "")
    assert done.stdout.strip() == "True"


@posix_only
def test_the_probe_has_an_address_space_and_cpu_cap() -> None:
    resource = pytest.importorskip("resource")
    code = (
        "import resource\n"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0],"
        " resource.getrlimit(resource.RLIMIT_CPU)[0])"
    )
    done = audit._run_probe_process([sys.executable, "-c", code], "")
    address_space, cpu = (int(part) for part in done.stdout.split())

    def capped(which: int, wanted: int) -> int:
        hard = resource.getrlimit(which)[1]
        return wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)

    assert address_space == capped(resource.RLIMIT_AS, audit.PROBE_ADDRESS_SPACE_BYTES)
    assert cpu == capped(
        resource.RLIMIT_CPU,
        audit.PROBE_TIMEOUT_SECONDS + audit.PROBE_CPU_SLACK_SECONDS,
    )


def test_a_missing_resource_module_does_not_stop_the_probe(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)  # import raises ImportError
    audit._limit_probe_resources()  # must simply return
