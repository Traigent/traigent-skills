"""Split quality the audit checks before a paid run.

traigent-skills#473: a split with too few rows of the rarer class cannot rank two
configurations, and the scalar label-dominance check never looks inside a
structured gold value. traigent-skills#475: a holdout whose inputs are
near-copies of tuning inputs (paraphrases) passed the exact-text overlap check.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _scan(path: Path, root: Path, **kwargs):
    reports, *_ = audit.scan_datasets([path], root, **kwargs)
    assert len(reports) == 1
    return reports[0]


def _structured_rows(positive: int, negative: int, split: str | None = None) -> list[dict]:
    rows = []
    for index in range(positive + negative):
        row = {
            "input": f"ticket number {index} reports failure code {index * 7}",
            "expected_output": {"is_flaky": index < positive, "checks": ["lint"]},
        }
        if split:
            row["split"] = split
        rows.append(row)
    return rows


def test_a_label_field_inside_structured_gold_is_counted_per_slice(tmp_path: Path) -> None:
    rows = _structured_rows(3, 47, "tuning") + _structured_rows(40, 0, "holdout")
    for index, row in enumerate(rows):
        row["input"] = f"row {index} unique text token{index}"
    path = _write(tmp_path / "data.jsonl", rows)
    report = _scan(path, tmp_path, label_field="is_flaky")
    joined = "\n".join(report.findings)
    assert "tuning slice has 3 row(s) of label `True`" in joined
    assert "under the 20-row minority minimum" in joined
    assert any("`is_flaky`" in note and "tuning" in note for note in report.notes)


def test_zero_positive_rows_in_a_slice_is_named_not_averaged_away(tmp_path: Path) -> None:
    rows = _structured_rows(0, 60)
    rows += _structured_rows(30, 0)
    for index, row in enumerate(rows):
        row["input"] = f"row {index} unique text token{index}"
        row["split"] = "tuning" if index < 60 else "holdout"
    # the tuning slice never shows the positive class, the holdout does
    path = _write(tmp_path / "data.jsonl", rows)
    report = _scan(path, tmp_path, label_field="is_flaky")
    assert any("tuning slice has 0 row(s) of label `True`" in f for f in report.findings)


def test_a_label_field_present_in_no_row_reports_class_balance_not_checked(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "data.jsonl", _structured_rows(30, 30))
    report = _scan(path, tmp_path, label_field="no_such_field")
    assert any("class balance not checked" in f for f in report.findings)


def test_structured_gold_without_a_label_field_notes_class_balance_not_checked(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "data.jsonl", _structured_rows(30, 30))
    report = _scan(path, tmp_path)
    assert any(
        "class balance not checked" in n and "--label-field" in n
        for n in report.notes
    )
    assert not any("class balance not checked" in f for f in report.findings)


def test_scalar_gold_keeps_the_existing_dominance_check_and_no_new_line(
    tmp_path: Path,
) -> None:
    rows = [{"input": f"q {i} t{i}", "expected_output": "yes"} for i in range(40)]
    report = _scan(_write(tmp_path / "data.jsonl", rows), tmp_path)
    assert not any("class balance not checked" in f for f in report.findings)
    assert any("one label covers 40 of 40" in f for f in report.findings)


def test_paraphrased_holdout_inputs_are_flagged_across_a_tagged_split(
    tmp_path: Path,
) -> None:
    base = (
        "please summarise the incident ticket for customer {n} covering the outage "
        "billing impact the root cause the remediation steps taken and the follow up "
        "actions agreed with the account owner during the review call"
    )
    tuning = [
        {"input": base.format(n=i), "expected_output": "a", "split": "tuning"}
        for i in range(40)
    ]
    holdout = [
        {
            "input": base.format(n=i).replace("summarise", "summarize"),
            "expected_output": "a",
            "split": "holdout",
        }
        for i in range(35)
    ]
    report = _scan(_write(tmp_path / "data.jsonl", tuning + holdout), tmp_path)
    assert any(
        "holdout input(s) have a near-duplicate in the tuning slice" in f
        for f in report.findings
    ), report.findings


def test_paraphrased_holdout_inputs_are_flagged_across_sibling_files(
    tmp_path: Path,
) -> None:
    base = (
        "please summarise the incident ticket for customer {n} covering the outage "
        "billing impact the root cause the remediation steps taken and the follow up "
        "actions agreed with the account owner during the review call"
    )
    _write(
        tmp_path / "tuning.jsonl",
        [{"input": base.format(n=i), "expected_output": "a"} for i in range(40)],
    )
    _write(
        tmp_path / "holdout.jsonl",
        [
            {"input": base.format(n=i).replace("summarise", "summarize"), "expected_output": "a"}
            for i in range(35)
        ],
    )
    reports, *_ = audit.scan_datasets(
        [tmp_path / "tuning.jsonl", tmp_path / "holdout.jsonl"], tmp_path
    )
    tuning = next(r for r in reports if r.file == "tuning.jsonl")
    assert any(
        "holdout input(s) have a near-duplicate" in f for f in tuning.findings
    ), tuning.findings


def test_distinct_holdout_inputs_raise_no_near_duplicate_finding(tmp_path: Path) -> None:
    rows = [
        {"input": f"alpha{i} beta{i} gamma{i} delta{i}", "expected_output": "a", "split": s}
        for i, s in enumerate(["tuning"] * 40 + ["holdout"] * 35)
    ]
    report = _scan(_write(tmp_path / "data.jsonl", rows), tmp_path)
    assert not any("near-duplicate in the tuning slice" in f for f in report.findings)
