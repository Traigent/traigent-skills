"""Shared fixtures for the Tier 2 tests.

The Tier 1 reports the Tier 2 tests read are PRODUCED here by running
`audit_project.py` on the committed fixture projects, not hand-written. A
hand-written report would let the two tiers drift apart silently: the field this
suite reads would keep existing in the test while disappearing from the real
report.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURES = TESTS_DIR / "fixtures"
TIER2 = SCRIPTS_DIR / "tier2_checks.py"

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tier2_fake_backend import SENTINEL_KEY  # noqa: E402


def _tier1_report(project: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{project.name}.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "audit_project.py"),
            "--root",
            str(project),
            "--json",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return report_path


@pytest.fixture(scope="session")
def healthy_tier1(tmp_path_factory) -> Path:
    """A Tier 1 report for the wired fixture: two model ids, a usable dataset."""
    return _tier1_report(FIXTURES / "healthy", tmp_path_factory.mktemp("tier1"))


@pytest.fixture(scope="session")
def weak_tier1(tmp_path_factory) -> Path:
    """A Tier 1 report whose scorer is NOT repeatable (next-step branch `d`)."""
    return _tier1_report(FIXTURES / "weak", tmp_path_factory.mktemp("tier1"))


@pytest.fixture()
def sentinel_key(monkeypatch) -> str:
    """Plant the key in THIS process so every child inherits it.

    Same discipline as the Tier 1 leak tests: never build an environment dict by
    copying the real one — inheritance says the same thing without the shape a
    credential scanner is right to flag.
    """
    monkeypatch.setenv("TRAIGENT_API_KEY", SENTINEL_KEY)
    return SENTINEL_KEY


@pytest.fixture()
def fake_traigent_cli(monkeypatch, tmp_path):
    """Put a recording stand-in for the `traigent` CLI first on PATH.

    The real CLI is never spawned by a test: it would reach a provider or the
    portal. The stand-in writes its own argv to a file, which is what the CLI
    checks are asserted against.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    record = tmp_path / "argv.jsonl"
    script = bin_dir / "traigent"
    # The `plan` payload is the shape the real portal returned on the dogfood
    # run of 2026-09-13 (tier2-live-probe.md item 6, FINDINGS.md §7.3-§7.4):
    # low evidence, the caller's own cap echoed back, a command that had been
    # retired from the SDK, and the cost objective oriented to maximize. It is
    # reproduced here so the relay is tested against what the service really
    # says, not against a tidy plan nobody has seen.
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"record = {str(record)!r}\n"
        "argv = sys.argv[1:]\n"
        "with open(record, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(argv) + '\\n')\n"
        "if argv[:1] == ['plan']:\n"
        "    print(json.dumps({'success': True, 'data': {\n"
        "        'advisory': True, 'evidence_level': 'low', 'phase': 'P1_STATIC',\n"
        "        'plan': {'max_trials': 6, 'cost_limit_usd': 5.0,\n"
        "                 'models': ['gpt-5-unreachable']},\n"
        "        'objectives': [{'name': 'accuracy', 'orientation': 'maximize'},\n"
        "                       {'name': 'cost', 'orientation': 'maximize'}],\n"
        "        'steps': [{'command': 'traigent next-steps'}]}}))\n"
        "else:\n"
        "    print(json.dumps({'ok': True, 'argv': argv}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.getenv('PATH', '')}")
    return record


def run_tier2(*args: str) -> subprocess.CompletedProcess:
    """Run the Tier 2 script exactly as a user would, in a child process."""
    return subprocess.run(
        [sys.executable, str(TIER2), *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def recorded_argv(record: Path) -> list[list[str]]:
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
