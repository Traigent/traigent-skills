"""`--help` exits 0 and a real usage error still exits 2, for both scripts.

Both mains catch the `SystemExit` argparse raises so that a usage error returns
2 instead of a traceback. That catch must not turn `--help`, which argparse
ends with exit 0, into a failure: a caller that checks a command against
`--help` under `set -e` or in a CI step would read help as a broken script.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import SCRIPTS_DIR

SCRIPTS = ["audit_project.py", "tier2_checks.py"]


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPTS_DIR / script), *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_exits_zero_and_prints_usage(script: str, flag: str) -> None:
    completed = _run(script, flag)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("usage:"), completed.stdout


@pytest.mark.parametrize("script", SCRIPTS)
def test_an_unknown_flag_is_still_a_usage_error(script: str) -> None:
    completed = _run(script, "--no-such-flag")
    assert completed.returncode == 2, completed.stdout
    assert "usage:" in completed.stderr
