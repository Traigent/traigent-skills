"""Exactly one next step, chosen by the most blocking finding.

Brief R3: recommend one next step with the reason in one sentence, in the
user's own numbers, and say that stopping is a valid choice. Four of the seven
branches are reachable from the committed fixture trees; the other three are
driven directly, so every branch is covered and the priority order is pinned.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
from conftest import strict_json

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


def _run(root: Path, out_dir: Path, *extra: str):
    report_path = out_dir / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return strict_json(report_path.read_text(encoding="utf-8")), completed.stdout


def _variant(tmp_path: Path, scorer_src: str) -> Path:
    """The healthy fixture with its scorer replaced: one changed file per case."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    (root / "scorer.py").write_text(scorer_src, encoding="utf-8")
    return root


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


def _scan_sibling_pair(tmp_path: Path, tuning_rows: list[dict], holdout_rows: list[dict]):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    paths = []
    for name, rows in (("tuning.jsonl", tuning_rows), ("holdout.jsonl", holdout_rows)):
        path = eval_dir / name
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        paths.append(path)
    reports, _, _, _ = audit.scan_datasets(paths, tmp_path)
    return {report.file: report for report in reports}


def _row(question: str, split: str | None = None) -> dict:
    row = {"input": question, "expected_output": "answer"}
    if split is not None:
        row["metadata"] = {"split": split}
    return row


def test_partially_tagged_single_file_reports_holdout_overlap(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in
                              [_row("Q1", "holdout"), _row(" q1 ")]) + "\n")
    reports, _, _, _ = audit.scan_datasets([path], tmp_path)
    assert reports[0].holdout_overlap == [0, 1]
    assert any("both the holdout slice" in finding for finding in reports[0].findings)


def test_untagged_named_holdout_rows_do_not_create_false_overlap(tmp_path):
    reports = _scan_sibling_pair(tmp_path, [_row("tuning only")],
                                [_row("Q1", "holdout"), _row(" q1 ")])
    assert reports["eval/holdout.jsonl"].holdout_overlap == []


@pytest.mark.parametrize("holdout_tag", ["holdout", None])
def test_explicit_tuning_in_named_holdout_still_reports_overlap(tmp_path, holdout_tag):
    reports = _scan_sibling_pair(tmp_path, [_row("tuning only")],
                                [_row("Q1", holdout_tag), _row(" q1 ", "tune")])
    assert reports["eval/holdout.jsonl"].holdout_overlap == [0, 1]


def test_tagged_sibling_pair_propagates_holdout_and_detects_normalized_overlap(
    tmp_path: Path,
) -> None:
    reports = _scan_sibling_pair(
        tmp_path,
        [_row("  SAME   question ", "tune"), _row("tuning only", "tune")],
        [_row("same question", "holdout"), _row("holdout only", "holdout")],
    )

    tuning = reports["eval/tuning.jsonl"]
    holdout = reports["eval/holdout.jsonl"]
    assert tuning.holdout_rows == 2
    assert holdout.holdout_rows == 2
    assert tuning.holdout_overlap == [0]
    assert any("sibling holdout file" in finding for finding in tuning.findings)


def test_tagged_sibling_pair_without_overlap_still_propagates_holdout(
    tmp_path: Path,
) -> None:
    reports = _scan_sibling_pair(
        tmp_path,
        [_row("tuning only", "tune")],
        [_row("holdout only", "holdout")],
    )

    tuning = reports["eval/tuning.jsonl"]
    assert tuning.holdout_rows == 1
    assert tuning.holdout_overlap == []


def test_untagged_rows_in_partially_tagged_holdout_file_inherit_filename_role(
    tmp_path: Path,
) -> None:
    reports = _scan_sibling_pair(
        tmp_path,
        [_row("SAME", "tune")],
        [_row("other", "holdout"), _row(" same ")],
    )

    tuning = reports["eval/tuning.jsonl"]
    holdout = reports["eval/holdout.jsonl"]
    assert holdout.holdout_rows == 2
    assert tuning.holdout_rows == 2
    assert tuning.holdout_overlap == [0]
    assert not any("contradict" in finding for finding in holdout.findings)


def test_mixed_row_tags_win_and_a_named_holdout_contradiction_is_reported(
    tmp_path: Path,
) -> None:
    reports = _scan_sibling_pair(
        tmp_path,
        [
            _row("actual holdout", "tune"),
            _row("already internal holdout", "holdout"),
        ],
        [
            _row("actual holdout", "holdout"),
            _row("not a holdout despite filename", "tune"),
        ],
    )

    tuning = reports["eval/tuning.jsonl"]
    holdout = reports["eval/holdout.jsonl"]
    assert tuning.holdout_rows == 1
    assert holdout.holdout_rows == 1
    assert tuning.holdout_overlap == [0]
    assert any("contradict" in finding for finding in holdout.findings)


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


def test_branch_f_fires_when_no_dataset_was_found() -> None:
    """No dataset at all is the largest dataset shortfall there is: it must not
    fall through to the all-clear branch."""
    entry = _entry([_knob("model", "read")])
    step = audit.next_step(_inventory([entry], [_scorer()]), [], GOOD_PROBE, _scorer())
    assert step["branch"] == "f"
    assert step["skills"] == ["traigent-dataset-curate"]
    assert step["line"].startswith("No evaluation dataset was found")
    assert "all check out" not in step["line"]


def test_a_project_with_no_dataset_is_routed_to_curate(tmp_path: Path) -> None:
    project = tmp_path / "nodata"
    project.mkdir()
    (project / "agent.py").write_text(
        "import traigent\n\n"
        "@traigent.optimize(configuration_space={'model': ['gpt-4o-mini', 'gpt-4o'],"
        " 'temperature': [0.0, 0.7]})\n"
        "def answer(question, model='gpt-4o-mini', temperature=0.0):\n"
        "    return f'{model}:{temperature}:{question}'\n",
        encoding="utf-8",
    )
    (project / "scorer.py").write_text(
        "def score(output, expected):\n"
        "    return 1.0 if output.strip() == expected.strip() else 0.0\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report, card = _run(project, out_dir)
    assert report["datasets"] == []
    assert report["next_step"]["branch"] == "f"
    assert report["next_step"]["skills"] == ["traigent-dataset-curate"]
    assert "all check out" not in card


def test_a_dataset_the_sdk_cannot_load_is_routed_to_curate() -> None:
    """`eval_dataset` reads only `input`/`input_data`: a large, split dataset
    keyed any other way still stops the first run, so it is never all-clear."""
    entry = _entry([_knob("model", "read")])
    dataset = _dataset(80, 40)
    dataset.input_key_counts = {"question": 80}
    dataset.rows_without_sdk_input = 80
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [dataset], GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "f"
    assert step["skills"] == ["traigent-dataset-curate"]
    assert "80 row(s) with no `input`/`input_data` key" in step["line"]
    assert "all check out" not in step["line"]


def test_a_row_with_no_input_like_key_is_counted_not_dropped(tmp_path: Path) -> None:
    """The SDK refuses the whole file on one row without `input`/`input_data`,
    even a row the audit's discovery keys do not recognise at all."""
    path = tmp_path / "data.jsonl"
    rows = [{"input": f"question {i}", "output": f"a{i}"} for i in range(40)]
    rows.append({"text": "a stray row", "output": "x"})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    reports, _, _, _ = audit.scan_datasets([path], tmp_path)
    assert reports[0].rows_without_sdk_input == 1
    assert any(
        "1 row(s) have no `input`/`input_data` key" in finding
        for finding in reports[0].findings
    ), reports[0].findings
    entry = _entry([_knob("model", "read")])
    step = audit.next_step(
        _inventory([entry], [_scorer()]), reports, GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "f"
    assert "1 row(s) with no `input`/`input_data` key" in step["line"]


def test_the_question_keys_fixture_is_flagged_and_routed(tmp_path: Path) -> None:
    report, card = _run(FIXTURES / "question-keys", tmp_path)
    by_file = {item["file"]: item for item in report["datasets"]}
    for name in ("eval/tuning.jsonl", "eval/holdout.jsonl"):
        assert any(
            "`question`" in finding and "`eval_dataset`" in finding
            for finding in by_file[name]["findings"]
        ), by_file[name]["findings"]
    assert report["next_step"]["branch"] == "f"
    assert "all check out" not in card


def test_an_input_keyed_dataset_gets_no_input_key_finding(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(
        "".join(
            json.dumps({"input": f"question {i}", "output": f"a{i}"}) + "\n"
            for i in range(40)
        ),
        encoding="utf-8",
    )
    reports, _, _, _ = audit.scan_datasets([path], tmp_path)
    assert not any("eval_dataset" in finding for finding in reports[0].findings)


def test_branch_f_judges_a_named_holdout_file_by_the_holdout_minimum_only() -> None:
    """A holdout file declared by its name beside a tuning file has no tuning
    rows to judge: 10 holdout rows under the holdout minimum is reported as a
    short holdout slice, never as a 10-row tuning file, and the tuning file is
    the one named when it is short too."""
    entry = _entry([_knob("model", "read")])
    tuning = _dataset(12, 10)
    tuning.file = "eval/tuning.jsonl"
    tuning.split_counts = {}
    holdout = _dataset(10, 10)
    holdout.file = "eval/holdout.jsonl"
    holdout.split_counts = {}
    holdout.holdout_by_name = True
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [tuning, holdout], GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "f"
    assert step["line"].startswith("eval/tuning.jsonl has 12 row(s) and a 10-row")
    assert "under the 30-row tuning minimum and the 30-row holdout minimum" in step["line"]
    # The tuning file is long enough; only the holdout is short, and the line
    # says exactly that (40 rows is not "under the tuning minimum").
    tuning.rows = 40
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [tuning, holdout], GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "f"
    assert step["line"].startswith("eval/tuning.jsonl has 40 row(s) and a 10-row")
    assert "under the 30-row holdout minimum, so" in step["line"]
    assert "tuning minimum" not in step["line"]
    # A holdout file with no tuning sibling short is described by its role.
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [holdout], GOOD_PROBE, _scorer()
    )
    assert step["branch"] == "f"
    assert step["line"].startswith(
        "eval/holdout.jsonl is a 10-row holdout slice declared by file name"
    )


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
    # It IS repeatable: the remedy is what it measures, not its repeatability.
    assert "make it repeatable" not in step["line"]
    assert "fix what it measures" in step["line"]


def test_an_unstable_scorer_is_told_to_make_it_repeatable() -> None:
    entry = _entry([_knob("model", "read")])
    unstable = {
        "ran": True,
        "scores": {"good": [0.1, 0.9], "partial": [0.5], "bad": [0.0]},
        "errors": [],
    }
    step = audit.next_step(
        _inventory([entry], [_scorer()]), [_dataset(80, 40)], unstable, _scorer()
    )
    assert "make it repeatable" in step["line"]


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


# --------------------------------------------------------------------------
# what the scorer probe may conclude from a partial or non-numeric outcome
# --------------------------------------------------------------------------

PROBE_CONDITIONS = "rule out the probe's own conditions"
NOT_ESTABLISHED = (
    "so it is not established that a run would get a usable score for every row"
)


def _three_way(
    good: str = "return 1.0",
    partial: str = "return 0.5",
    bad: str = "return 0.0",
    head: str = "",
) -> str:
    """The healthy fixture's exact-match scorer, one statement per probe case.

    The probe calls it with (good, good), (good minus its last word, good) and
    (an unrelated row's answer, good), so each branch below is one case.
    """
    return (
        f"{head}def score(output, expected):\n"
        f"    if output == expected:\n        {good}\n"
        f"    if expected.startswith(output):\n        {partial}\n"
        f"    {bad}\n"
    )


RAISE_ON_PARTIAL = _three_way(partial="raise RuntimeError('partial')")
QUALITY_VALUE = (
    "def quality_value(answer, reference):\n"
    "    return 1.0 if answer == reference else 0.0\n"
)

REPROS = {
    "healthy": (_three_way(), None, "ok", "g"),
    "posinf": (_three_way(good="return float('inf')"), None, "attention", "d"),
    "partial_raise": (RAISE_ON_PARTIAL, None, "attention", "d"),
    "renamed": (QUALITY_VALUE, "quality_value", "ok", "g"),
}


@pytest.mark.parametrize("case", sorted(REPROS))
def test_issue_repros_agree_end_to_end(case: str, tmp_path: Path) -> None:
    """The JSON, the area and the next step tell one story for each issue."""
    source, selector, status, branch = REPROS[case]
    root = _variant(tmp_path, source)
    extra = ("--scorer", f"{root}/scorer.py:{selector}") if selector else ()
    report, card = _run(root, tmp_path, *extra)
    assert report["areas"]["scorer"]["status"] == status
    assert report["next_step"]["branch"] == branch
    assert report["next_step"]["line"] in card
    if branch != "g":
        assert "all check out" not in card
        assert "ordered as expected" not in card
    if selector:
        assert report["scorers"][0]["function"] == selector
        assert report["scorers"][0]["selected"] is True
        assert f"probed `{selector}` at scorer.py:" in card


NON_FINITE = {
    "nan": (_three_way(good="return float('nan')"), 1),
    "posinf": (_three_way(good="return float('inf')"), 1),
    "neginf": (
        _three_way(partial="return float('-inf')", bad="return float('-inf')"),
        2,
    ),
    "nan_all": (_three_way(*["return float('nan')"] * 3), 3),
    # Teeth: a finite number outside 0..1 is a score, not a defect.
    "finite_control": (_three_way(good="return 2.0"), 0),
}


@pytest.mark.parametrize("case", sorted(NON_FINITE))
def test_non_finite_scores_never_reach_the_all_clear(case: str, tmp_path: Path) -> None:
    source, withheld = NON_FINITE[case]
    report, card = _run(_variant(tmp_path, source), tmp_path)
    text = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "Infinity" not in text
    assert "NaN" not in text
    marked = [e for e in report["scorer_probe"]["errors"] if e.get("non_finite")]
    assert len(marked) == withheld, report["scorer_probe"]
    if not withheld:
        assert report["next_step"]["branch"] == "g"
        assert report["areas"]["scorer"]["status"] == "ok"
        return
    assert all(error["error_type"] is None for error in marked)
    assert report["next_step"]["branch"] == "d"
    assert report["areas"]["scorer"]["status"] == "attention"
    line = report["next_step"]["line"]
    assert (
        f"{withheld} probe call(s) returned a value that is not a finite number"
        in line
    )
    assert "make it return a finite number" in line
    assert "not a finite number" in card


MIXED = {
    "partial_raise": RAISE_ON_PARTIAL,
    "good_raise_repeat": _three_way(
        head="CALLS = []\n\n\n",
        good="CALLS.append(1)\n"
        "        if len(CALLS) > 1:\n"
        "            raise RuntimeError('repeat')\n"
        "        return 1.0",
    ),
    # 10**400 is finite; float() of it raises OverflowError in the probe.
    "hugeint_good": _three_way(good="return 10**400"),
    # None is not a number, so the probe raises TypeError for that call.
    "none_on_partial": _three_way(partial="return None"),
    # A return the probe does not read, on the exact match only.
    "np_float32_good": _three_way(
        good="return np.float32(1.0)", head="import numpy as np\n\n\n"
    ),
}


@pytest.mark.parametrize("case", sorted(MIXED))
def test_mixed_outcomes_go_to_d_with_neutral_wording(case: str, tmp_path: Path) -> None:
    """Some calls scored and some raised: report what was observed, name the
    probe's own conditions first, and claim no cause."""
    if case.startswith("np_"):
        pytest.importorskip("numpy")
    report, card = _run(_variant(tmp_path, MIXED[case]), tmp_path)
    line = report["next_step"]["line"]
    assert report["next_step"]["branch"] == "d"
    assert "scored some probe calls and 1 probe call(s) raised" in line
    assert NOT_ESTABLISHED in line
    assert PROBE_CONDITIONS in line
    assert line.index(PROBE_CONDITIONS) < line.index("traigent-eval-build")
    # The remedy names the return values the probe reads, and states only
    # conditions the probe really has.
    assert "reads a return value only as" in line
    assert "described under Safety in the traigent-setup-audit skill" in line
    assert "has no network access" not in line
    meaning = report["areas"]["scorer"]["meaning"]
    assert meaning.startswith("Not every probe call produced a finite score")
    assert "returns different numbers for the same pair" not in meaning
    for phrase in ("measuring the scorer", "convention", "ordered as expected"):
        assert phrase not in card
    if case == "good_raise_repeat":
        assert "returned one identical score" not in card


EVERY_CALL = {
    "all_raise": (_three_way(*["raise RuntimeError('always')"] * 3), "RuntimeError"),
    "async": ("async def score(output, expected):\n    return 1.0\n", "TypeError"),
    "acc_dict": (_three_way(*["return {'accuracy': 1.0}"] * 3), "TypeError"),
    "hugeint_all": (_three_way(*["return 10**400"] * 3), "OverflowError"),
    "np_int64": (
        _three_way(*["return np.int64(1)"] * 3, head="import numpy as np\n\n\n"),
        "TypeError",
    ),
    "np_float32": (
        _three_way(*["return np.float32(1.0)"] * 3, head="import numpy as np\n\n\n"),
        "TypeError",
    ),
}


@pytest.mark.parametrize("case", sorted(EVERY_CALL))
def test_every_call_failure_keeps_branch_e(case: str, tmp_path: Path) -> None:
    """Pinned as today's routing: nothing scored, so nothing was measured."""
    source, raised = EVERY_CALL[case]
    if case.startswith("np_"):
        pytest.importorskip("numpy")
    report, card = _run(_variant(tmp_path, source), tmp_path)
    assert report["next_step"]["branch"] == "e"
    assert report["areas"]["scorer"]["status"] == "attention"
    assert f"every probe call raised {raised}" in card


def test_a_non_ascii_exception_class_is_kept_and_routes_to_d(tmp_path: Path) -> None:
    """A type name the report cannot carry is withheld; the record is not."""
    source = _three_way(
        head="class Échec(Exception):\n    pass\n\n\n",
        partial="raise Échec('partial')",
    )
    report, card = _run(_variant(tmp_path, source), tmp_path)
    errors = report["scorer_probe"].get("errors")
    assert isinstance(errors, list) and len(errors) == 1, report["scorer_probe"]
    assert errors[0]["case"] == "partial"
    assert errors[0]["error_type"] is None
    assert re.fullmatch(r"scorer\.py:\d+", errors[0]["error_site"] or "")
    assert report["next_step"]["branch"] == "d"
    assert re.search(r"raised an error at scorer\.py:\d+", card), card


SELECTIONS = {
    # case: (scorer.py, --scorer function, entry flagged selected, branch, status)
    "inventoried": (
        _three_way() + "\n\ndef evaluate_other(output, expected):\n    return 0.0\n",
        "score",
        "score",
        "g",
        "ok",
    ),
    "private": (
        _three_way().replace("def score(", "def _score("),
        "_score",
        "_score",
        "g",
        "ok",
    ),
    "refused": (
        "import subprocess\n\n\n" + QUALITY_VALUE,
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
    "missing_with_inventory": (_three_way(), "nope", None, "e", "attention"),
    "missing_empty_inventory": (QUALITY_VALUE, "nope", None, "c", "attention"),
    # Bound by the module however it is nested in its top-level statements:
    # the probe loaded and scored it, so it is a found scorer.
    "in_try": (
        "try:\n"
        "    def quality_value(answer, reference):\n"
        "        return 1.0 if answer == reference else 0.0\n"
        "except ImportError:\n    pass\n",
        "quality_value",
        "quality_value",
        "g",
        "ok",
    ),
    "in_if": (
        "if True:\n"
        "    def quality_value(answer, reference):\n"
        "        return 1.0 if answer == reference else 0.0\n",
        "quality_value",
        "quality_value",
        "g",
        "ok",
    ),
    # Refused, so never loaded: found by name is enough to count it.
    "refused_method": (
        "import subprocess\n\n\nclass C:\n"
        "    def quality_value(self, a, b):\n        return 1.0\n",
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
    # Found by name, so present, though the probe's loader cannot bind it: the
    # card shows that real probe failure instead of "no scorer found".
    "rebound": (
        QUALITY_VALUE + "\n\nquality_value = None\n",
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
    "method": (
        "class C:\n    def quality_value(self, a, b):\n        return 1.0\n",
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
    "nested": (
        "def outer():\n    def quality_value(a, b):\n        return 1.0\n",
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
    "main_guard": (
        'if __name__ == "__main__":\n'
        "    def quality_value(a, b):\n        return 1.0\n",
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
    # The module's own LookupError at import is not the loader's "not bound".
    "lookup_at_import": (
        "raise LookupError('at import')\n\n\n" + QUALITY_VALUE,
        "quality_value",
        "quality_value",
        "e",
        "attention",
    ),
}
LOAD_FAILURES = {"rebound", "method", "nested", "main_guard", "lookup_at_import"}


@pytest.mark.parametrize("case", sorted(SELECTIONS))
def test_explicit_selection(case: str, tmp_path: Path) -> None:
    source, function, selected, branch, status = SELECTIONS[case]
    root = _variant(tmp_path, source)
    report, card = _run(root, tmp_path, "--scorer", f"{root}/scorer.py:{function}")
    assert report["next_step"]["branch"] == branch
    assert report["areas"]["scorer"]["status"] == status
    flagged = [entry for entry in report["scorers"] if "selected" in entry]
    assert [entry["function"] for entry in flagged] == ([selected] if selected else [])
    assert all(entry["selected"] is True for entry in flagged)
    assert all(entry["line"] > 0 for entry in flagged)
    skipped = {item["function"] for item in report["skipped_scorer_candidates"]}
    assert function not in skipped
    if case == "inventoried":
        assert {e["function"] for e in report["scorers"]} == {"score", "evaluate_other"}
    if case == "refused":
        assert "was selected with --scorer and refused" in card
        assert "1 scorer(s) were found (1 executing)" in report["next_step"]["line"]
    if case.startswith("missing"):
        assert "the function was not found in the module" in card
    if branch == "c":
        assert report["scorers"] == []
    if case in LOAD_FAILURES:
        assert report["scorer_probe"]["stage"] == "load"
        assert "raised LookupError" in card
        assert "while loading, so it never ran" in card


@pytest.mark.parametrize("function", ["score", "_score"])
def test_a_relative_selector_with_dotdot_names_the_inventoried_file_once(
    function: str, tmp_path: Path
) -> None:
    """`sub/../scorer.py`, from a working directory outside --root, is the same
    file as the inventoried `scorer.py`: one entry, and no skipped twin."""
    source = _three_way().replace("def score(", f"def {function}(")
    root = _variant(tmp_path, source)
    (root / "sub").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            "--scorer",
            f"sub/../scorer.py:{function}",
        ],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = strict_json(report_path.read_text(encoding="utf-8"))
    named = [entry for entry in report["scorers"] if entry["function"] == function]
    assert len(named) == 1, report["scorers"]
    assert named[0]["selected"] is True
    skipped = {item["function"] for item in report["skipped_scorer_candidates"]}
    assert function not in skipped
    assert report["next_step"]["branch"] == "g"


def test_a_symlink_loop_selection_is_refused_not_a_traceback(tmp_path: Path) -> None:
    """A selected file that is a symlink loop cannot be read: it is refused
    like any unparsable module, and the audit still finishes."""
    root = _variant(tmp_path, _three_way())
    try:
        os.symlink("loop.py", root / "loop.py")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable here: {exc}")
    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            "--scorer",
            "loop.py:score",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert "Traceback" not in completed.stderr, completed.stderr
    assert completed.returncode == 0, completed.stderr
    report = strict_json(report_path.read_text(encoding="utf-8"))
    refusal = report["scorer_selection_refused"]
    assert refusal.startswith("`score` at loop.py was selected"), refusal
    assert "the module could not be parsed" in refusal
    assert report["scorer_probe"] is None
    assert refusal in completed.stdout


def test_a_selection_that_does_not_exist_is_refused_not_a_traceback(
    tmp_path: Path,
) -> None:
    root = _variant(tmp_path, _three_way())
    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            "--scorer",
            "nope.py:score",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert "Traceback" not in completed.stderr, completed.stderr
    assert completed.returncode == 0, completed.stderr
    report = strict_json(report_path.read_text(encoding="utf-8"))
    refusal = report["scorer_selection_refused"]
    assert refusal.startswith("`score` at nope.py was selected"), refusal
    assert "the module could not be parsed" in refusal
    assert report["scorer_probe"] is None


def test_a_relative_root_with_an_external_selector_probes_that_file(
    tmp_path: Path,
) -> None:
    """`--root project --scorer ../outside.py:score` from the directory holding
    `project` is joined to the root once: `outside.py` beside it is probed, not
    a doubled `project/project/../outside.py` that does not exist."""
    root = _variant(tmp_path, _three_way())
    # Unlike the project's own `score`, this one returns inf for a match, so
    # the verdict shows which file was probed.
    outside = tmp_path / "outside.py"
    outside.write_text(_three_way(good="return float('inf')"), encoding="utf-8")
    report_path = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            root.name,
            "--json",
            str(report_path),
            "--scorer",
            "../outside.py:score",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = strict_json(report_path.read_text(encoding="utf-8"))
    assert report["scorer_selection_refused"] is None
    assert report["scorer_probe"] is not None
    selected = [entry["file"] for entry in report["scorers"] if "selected" in entry]
    assert selected == [Path(os.path.realpath(outside)).as_posix()]
    assert report["next_step"]["branch"] == "d"


@pytest.mark.parametrize("equality", ["native", "folds_case"])
def test_two_files_that_differ_only_in_case_stay_separate(
    equality: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """`scorer.py` and `SCORER.py` are two files on a case-sensitive
    directory: selecting one never probes the other. `folds_case` makes path
    equality ignore case, as WindowsPath's does on a case-sensitive NTFS
    directory, so the Windows behaviour is exercised on this machine too."""
    root = _variant(tmp_path, _three_way())
    twin = root / "SCORER.py"
    if twin.exists():
        pytest.skip("case-insensitive filesystem: SCORER.py is scorer.py here")
    twin.write_text(
        "import subprocess\n\n\ndef score(output, expected):\n"
        "    subprocess.run(['true'])\n    return 1.0\n",
        encoding="utf-8",
    )
    # Run in-process without patching this test process's sockets.
    monkeypatch.setattr(audit, "install_network_guard", lambda: None)
    monkeypatch.setattr(audit, "verify_network_guard", lambda: "active")
    if equality == "folds_case":

        def folded(self, other):
            if not isinstance(other, PurePosixPath):
                return NotImplemented
            return str(self).casefold() == str(other).casefold()

        monkeypatch.setattr(PurePosixPath, "__eq__", folded)
    out = tmp_path / "report.json"
    code = audit.main(
        ["--root", str(root), "--json", str(out), "--scorer", "scorer.py:score"]
    )
    captured = capsys.readouterr()
    monkeypatch.undo()
    assert code == 0, captured.err
    report = strict_json(out.read_text(encoding="utf-8"))
    files = sorted(entry["file"] for entry in report["scorers"])
    assert files == ["SCORER.py", "scorer.py"], report["scorers"]
    selected = [entry["file"] for entry in report["scorers"] if "selected" in entry]
    assert selected == ["scorer.py"]
    assert report["scorer_selection_refused"] is None
    assert report["scorer_probe"] is not None


@pytest.mark.parametrize(
    "literal",
    ["[0.0, 1e999]", "Choices(0.0, 1e999)", '[0.0, {"t": 1e999}]'],
    ids=["list", "choices", "dict"],
)
def test_a_non_finite_knob_value_is_reported_as_unreadable(
    literal: str, tmp_path: Path
) -> None:
    """`1e999` parses to inf, which strict JSON cannot carry: the knob is
    listed without values, and the report is still written."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    agent = root / "agent.py"
    source = agent.read_text(encoding="utf-8")
    widened = source.replace('"temperature": [0.0, 0.7]', f'"temperature": {literal}')
    assert widened != source
    agent.write_text(widened, encoding="utf-8")
    report, card = _run(root, tmp_path)
    assert "Infinity" not in (tmp_path / "report.json").read_text(encoding="utf-8")
    knobs = {
        knob["name"]: knob
        for entry in report["entry_points"]
        for knob in entry["knobs"]
    }
    assert knobs["temperature"]["values_readable"] is False
    assert knobs["temperature"]["values"] == []
    assert knobs["top_k"]["values_readable"] is True
    assert "has values the audit could not read" in card


@pytest.mark.parametrize("target", ["existing_file", "missing_dir"])
def test_a_report_that_cannot_be_strict_json_is_not_written(
    target: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The backstop for a non-finite number from any other source: refuse
    the whole report rather than write `Infinity`, and write nothing."""
    # Run in-process without patching this test process's sockets.
    monkeypatch.setattr(audit, "install_network_guard", lambda: None)
    monkeypatch.setattr(audit, "verify_network_guard", lambda: "active")
    real_build_report = audit.build_report

    def build_report(*args, **kwargs) -> dict:
        report = real_build_report(*args, **kwargs)
        report["poisoned"] = float("inf")
        return report

    monkeypatch.setattr(audit, "build_report", build_report)
    if target == "existing_file":
        out = tmp_path / "report.json"
        out.write_text('"sentinel"\n', encoding="utf-8")
    else:
        out = tmp_path / "not-yet" / "report.json"
    code = audit.main(["--root", str(FIXTURES / "healthy"), "--json", str(out)])
    captured = capsys.readouterr()
    assert code == 2, captured.out
    assert captured.err.startswith("audit_project.py:"), captured.err
    assert "## Next step" not in captured.out
    if target == "existing_file":
        assert out.read_text(encoding="utf-8") == '"sentinel"\n'
    else:
        assert not out.parent.exists()


def test_readiness_is_one_predicate() -> None:
    """The area status, the next step and Tier 2 read the same `ready`."""
    inventory = _inventory([_entry([_knob("model", "read")])], [_scorer()])
    datasets = [_dataset(80, 40)]

    def step(probe: dict) -> dict:
        return audit.next_step(inventory, datasets, probe, _scorer())

    cases = ("good", "partial", "bad")
    assert audit.probe_metrics(GOOD_PROBE).get("ready") is True
    assert audit.summarize_probe(GOOD_PROBE)[0] == "ok"
    assert step(GOOD_PROBE)["branch"] == "g"

    raised = {
        "ran": True,
        "scores": {"good": [1.0, 1.0], "partial": [], "bad": [0.0]},
        "errors": [
            {"case": "partial", "error_type": "RuntimeError", "error_site": "scorer.py:6"}
        ],
    }
    assert step(raised)["branch"] == "d"
    assert audit.probe_metrics(raised)["ready"] is False
    assert audit.summarize_probe(raised)[0] == "attention"

    every_call_raised = {
        "ran": True,
        "scores": {case: [] for case in cases},
        "errors": [
            {"case": case, "error_type": "RuntimeError", "error_site": "scorer.py:2"}
            for case in cases
        ],
    }
    assert step(every_call_raised)["branch"] == "e"

    withheld = {
        "ran": True,
        "scores": {case: [] for case in cases},
        "errors": [
            {"case": case, "error_type": None, "error_site": None, "non_finite": True}
            for case in cases
        ],
    }
    assert step(withheld)["branch"] == "d"
    assert "make it return a finite number" in step(withheld)["line"]

    # No error recorded, yet the partial case has no score: an honest probe
    # never produces that, so it is read as a malformed result.
    incomplete = {
        "ran": True,
        "scores": {"good": [1.0, 1.0], "partial": [], "bad": [0.0]},
        "errors": [],
    }
    metrics = audit.probe_metrics(incomplete)
    assert (metrics["verdict"], metrics.get("stage")) == ("failed", "tampered-result")
    assert step(incomplete)["branch"] == "e"

    # A stored report can still hold inf scores with no error, and inf > 0.5
    # would otherwise read as stable and ordered.
    infinite = {
        "ran": True,
        "scores": {"good": [float("inf")] * 5, "partial": [0.5], "bad": [0.0]},
        "errors": [],
    }
    metrics = audit.probe_metrics(infinite)
    assert (metrics["stable"], metrics["ordered"]) == (True, True)
    assert (metrics["finite"], metrics["ready"]) == (False, False)
    status, evidence = audit.summarize_probe(infinite)
    assert status == "attention"
    assert not any("ordered as expected" in line for line in evidence)
    assert step(infinite)["branch"] == "d"

    # An older parent dropped error records it could not name, leaving only a
    # count: complete-looking scores with a dropped key are not complete.
    legacy = {
        "ran": True,
        "scores": {"good": [1.0], "partial": [0.5], "bad": [0.0]},
        "dropped_keys": 1,
    }
    metrics = audit.probe_metrics(legacy)
    assert (metrics["verdict"], metrics.get("stage")) == ("failed", "tampered-result")
    assert step(legacy)["branch"] == "e"
    assert audit.probe_metrics({**legacy, "dropped_keys": 0})["ready"] is True
