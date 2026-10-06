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
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
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


def _refuse_constant(name: str) -> float:
    raise ValueError(f"{name} is not a JSON number")


def strict_json(text: str) -> object:
    """Parse as standard JSON: `NaN`, `Infinity` and `-Infinity` are refused.

    Python's own `json.loads` accepts them, so a report carrying one would
    parse here and break the first strict reader downstream.
    """
    try:
        return json.loads(text, parse_constant=_refuse_constant)
    except ValueError as exc:
        raise AssertionError(f"not strict JSON: {exc}") from exc


# --------------------------------------------------------------------------
# one-change variants of the healthy fixture
# --------------------------------------------------------------------------

HEALTHY_SIGNATURE = "def answer_question(question, model, temperature, top_k):"
HEALTHY_BODY = '    prefix = f"[{model}/{temperature}/{top_k}]"\n    return f"{prefix} {question}"'


def _replace_once(path: Path, old: str, new: str) -> None:
    """Edit the copy, failing loudly if the fixture no longer holds `old`: a
    silent no-op would leave a healthy project under a mutation's name."""
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"{path.name} no longer contains {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _rows(root: Path) -> list[dict]:
    text = (root / "dataset.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _write_rows(root: Path, rows: list[dict]) -> None:
    (root / "dataset.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _partly_unread(root: Path) -> None:
    agent = root / "agent.py"
    _replace_once(
        agent, HEALTHY_SIGNATURE, "def answer_question(question, model, temperature):"
    )
    _replace_once(
        agent,
        'prefix = f"[{model}/{temperature}/{top_k}]"',
        'prefix = f"[{model}/{temperature}]"',
    )


def _space_not_inventoried(root: Path) -> None:
    agent = root / "agent.py"
    text = agent.read_text(encoding="utf-8")
    changed, count = re.subn(
        r"configuration_space=\{.*?\n    \}",
        "configuration_space=build_space()",
        text,
        flags=re.S,
    )
    if count != 1:
        raise AssertionError("agent.py no longer holds one configuration_space dict")
    agent.write_text(changed, encoding="utf-8")
    _replace_once(
        agent, "import traigent\n", "import traigent\n\n\ndef build_space():\n    return {}\n"
    )


def _kwargs(root: Path) -> None:
    agent = root / "agent.py"
    _replace_once(agent, HEALTHY_SIGNATURE, "def answer_question(question, **kwargs):")
    _replace_once(agent, HEALTHY_BODY, "    return call_model(question, **kwargs)")


def _unparsed_helper(root: Path) -> None:
    (root / "helpers.py").write_text("def broken(:\n    pass\n", encoding="utf-8")


def _no_gold(root: Path) -> None:
    rows = _rows(root)
    if not all("expected_output" in row for row in rows):
        raise AssertionError("dataset.jsonl no longer carries expected_output on every row")
    _write_rows(
        root, [{k: v for k, v in row.items() if k != "expected_output"} for row in rows]
    )


def _holdout_leak(root: Path) -> None:
    rows = _rows(root)
    tuning = [row for row in rows if row["metadata"]["split"] != "holdout"]
    leaked = []
    j = 0
    for row in rows:
        if row["metadata"]["split"] == "holdout":
            source = tuning[j % 40]
            j += 1
            row = {
                **row,
                "input": source["input"],
                "expected_output": source["expected_output"],
            }
        leaked.append(row)
    if j == 0:
        raise AssertionError("dataset.jsonl no longer has a holdout slice")
    _write_rows(root, leaked)


def _duplicate_rows(root: Path) -> None:
    rows = _rows(root)
    rows[1] = {**rows[1], "input": rows[0]["input"]}
    _write_rows(root, rows)


HEALTHY_MUTATIONS: dict[str, Callable[[Path], None]] = {
    # `top_k` dropped from the signature and the body; still declared.
    "partly_unread": _partly_unread,
    # The space comes from a call the static reader cannot follow.
    "space_not_inventoried": _space_not_inventoried,
    # Every knob reaches the body only through `**kwargs`.
    "kwargs": _kwargs,
    # A second module with a syntax error, so the inventory is incomplete.
    "unparsed_helper": _unparsed_helper,
    # `expected_output` removed from every row.
    "no_gold": _no_gold,
    # Every holdout row repeats the input and gold of tuning row `j % 40`.
    "holdout_leak": _holdout_leak,
    # Row 1 takes row 0's input.
    "duplicate_rows": _duplicate_rows,
}


def healthy_variant(tmp_path: Path, mutation: str) -> Path:
    """Copy tests/fixtures/healthy to tmp_path/<mutation>/project and apply one mutation."""
    root = tmp_path / mutation / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    HEALTHY_MUTATIONS[mutation](root)
    return root


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
