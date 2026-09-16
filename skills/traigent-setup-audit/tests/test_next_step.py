"""Exactly one next step, chosen by the most blocking finding.

Brief R3: recommend one next step with the reason in one sentence, in the
user's own numbers, and say that stopping is a valid choice. Four of the seven
branches are reachable from the committed fixture trees; the other three are
driven directly, so every branch is covered and the priority order is pinned.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "audit_project.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()

ALL_ROUTED_SKILLS = {
    "traigent-setup-quickstart",
    "traigent-setup-decorator",
    "traigent-optimize-config-space",
    "traigent-eval-build",
    "traigent-eval-audit",
    "traigent-dataset-curate",
    "traigent-optimize-run",
}


# --------------------------------------------------------------------------
# end to end, from the committed fixture trees
# --------------------------------------------------------------------------


def _run(root: Path, out_dir: Path):
    report_path = out_dir / "report.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--json", str(report_path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(report_path.read_text(encoding="utf-8")), completed.stdout


@pytest.mark.parametrize(
    "fixture,branch,skill",
    [
        ("bare", "a", "traigent-setup-quickstart"),
        ("weak", "d", "traigent-eval-build"),
        ("netscorer", "e", "traigent-eval-audit"),
        ("healthy", "g", "traigent-optimize-run"),
    ],
)
def test_each_fixture_reaches_its_branch(
    fixture: str, branch: str, skill: str, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / fixture, tmp_path)
    assert report["next_step"]["branch"] == branch
    assert skill in report["next_step"]["skills"]
    assert report["next_step"]["line"] in card


@pytest.mark.parametrize("fixture", ["healthy", "weak", "bare", "netscorer", "skipped"])
def test_exactly_one_next_step_section_with_the_stop_line(
    fixture: str, tmp_path: Path
) -> None:
    report, card = _run(FIXTURES / fixture, tmp_path)
    assert card.count("## Next step") == 1
    assert card.count(report["next_step"]["line"]) == 1
    assert audit.STOP_LINE in card
    # It sits immediately before the deferred-questions section.
    assert card.index("## Next step") < card.index(
        "## What code alone could not tell you"
    )
    assert set(report["next_step"]["skills"]) <= ALL_ROUTED_SKILLS


def test_the_weak_fixture_does_not_take_the_knob_branch(tmp_path: Path) -> None:
    """`temperature` is unread but `model` is read, so not ALL knobs are unread."""
    report, _ = _run(FIXTURES / "weak", tmp_path)
    knobs = {k["name"]: k["status"] for k in report["entry_points"][0]["knobs"]}
    assert knobs == {"model": "read", "temperature": "declared, never read"}
    assert report["next_step"]["branch"] == "d"


# --------------------------------------------------------------------------
# the three branches the fixture trees cannot reach
# --------------------------------------------------------------------------


def _inventory(entry_points=(), scorers=(), files_scanned=7):
    inventory = audit.PythonInventory(files_scanned=files_scanned)
    inventory.entry_points = list(entry_points)
    inventory.scorers = list(scorers)
    return inventory


def _entry(knobs):
    return audit.EntryPoint(
        function="answer", file="agent.py", line=9, knobs=list(knobs)
    )


def _knob(name, status):
    return audit.Knob(
        name=name,
        values=[],
        values_readable=True,
        status=status,
        file="agent.py",
        line=5,
    )


def _scorer(kind="deterministic"):
    return audit.ScorerCandidate(
        function="score",
        file="scorer.py",
        line=1,
        kind=kind,
        signals=[],
        parameters=["output", "expected"],
    )


def _dataset(rows, holdout_rows):
    return audit.DatasetReport(
        file="data.jsonl",
        rows=rows,
        input_key_counts={"input": rows},
        expected_key_counts={"expected_output": rows},
        missing_expected=[],
        exact_duplicate_groups=[],
        near_duplicate_pairs=[],
        split_counts={"holdout": holdout_rows} if holdout_rows else {},
        holdout_rows=holdout_rows,
        holdout_overlap=[],
        label_counts={},
        findings=[],
    )


GOOD_PROBE = {
    "ran": True,
    "scores": {"good": [1.0, 1.0], "partial": [0.5], "bad": [0.0]},
    "errors": [],
}


def test_branch_b_fires_on_a_decorated_function_with_no_knobs() -> None:
    step = audit.next_step(_inventory([_entry([])], [_scorer()]), [], GOOD_PROBE, _scorer())
    assert step["branch"] == "b"
    assert step["skills"] == ["traigent-optimize-config-space"]
    assert "agent.py:9 declares 0 knobs" in step["line"]


def test_branch_b_also_fires_when_every_knob_is_unread() -> None:
    entry = _entry([_knob("temperature", "declared, never read")])
    step = audit.next_step(_inventory([entry], [_scorer()]), [], GOOD_PROBE, _scorer())
    assert step["branch"] == "b"
    assert "reads none of them" in step["line"]


def test_branch_b_does_not_fire_when_one_knob_is_read() -> None:
    entry = _entry(
        [_knob("model", "read"), _knob("temperature", "declared, never read")]
    )
    step = audit.next_step(_inventory([entry], [_scorer()]), [], GOOD_PROBE, _scorer())
    assert step["branch"] != "b"


def test_branch_c_fires_when_no_scorer_was_found() -> None:
    entry = _entry([_knob("model", "read")])
    step = audit.next_step(_inventory([entry], []), [], None, None)
    assert step["branch"] == "c"
    assert step["skills"] == ["traigent-eval-build"]
    assert "7 Python file(s)" in step["line"]


def test_branch_f_fires_on_a_dataset_under_the_minimums() -> None:
    entry = _entry([_knob("model", "read")])
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [_dataset(12, 0)], GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "f"
    assert step["skills"] == ["traigent-dataset-curate"]
    assert "12 row(s) and a 0-row holdout slice" in step["line"]


def test_branch_g_needs_every_earlier_branch_to_be_clear() -> None:
    entry = _entry([_knob("model", "read")])
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [_dataset(80, 40)], GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "g"
    assert step["skills"] == ["traigent-optimize-run"]
    assert "mock dry-run first" in step["line"]


def test_a_misordered_but_stable_scorer_takes_the_scorer_branch() -> None:
    entry = _entry([_knob("model", "read")])
    misordered = {
        "ran": True,
        "scores": {"good": [0.2, 0.2], "partial": [0.5], "bad": [0.9]},
        "errors": [],
    }
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [_dataset(80, 40)], misordered, _scorer()
    )
    assert step["branch"] == "d"
    assert "did not rank a known-good answer above a known-bad one" in step["line"]


def test_the_dataset_branch_never_outranks_an_unreliable_scorer() -> None:
    """Priority order is load-bearing: a scorer you cannot trust makes a bigger
    dataset measure nothing more reliably."""
    entry = _entry([_knob("model", "read")])
    unstable = {
        "ran": True,
        "scores": {"good": [0.1, 0.9], "partial": [0.5], "bad": [0.0]},
        "errors": [],
    }
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [_dataset(5, 0)], unstable, _scorer()
    )
    assert step["branch"] == "d"


def test_interpreter_probe_order_is_venv_then_venv_traigent(tmp_path: Path) -> None:
    """`.venv-traigent` (the throwaway environment a guided first run may create)
    is probed after `.venv` and before the audit's own interpreter."""
    root = tmp_path / "proj"
    (root / ".venv-traigent" / "bin").mkdir(parents=True)
    fallback = root / ".venv-traigent" / "bin" / "python"
    fallback.write_text("")
    assert audit.project_interpreter(root) == str(fallback)
    (root / ".venv" / "bin").mkdir(parents=True)
    preferred = root / ".venv" / "bin" / "python"
    preferred.write_text("")
    assert audit.project_interpreter(root) == str(preferred)
    assert audit.project_interpreter(tmp_path / "empty") == sys.executable
