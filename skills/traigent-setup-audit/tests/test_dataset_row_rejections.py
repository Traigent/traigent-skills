"""Rows with valid JSON but the wrong shape must remain visible in the audit."""

import json
import shutil
from pathlib import Path

import audit_project as audit
import pytest
from test_reporting_gaps import _run

FIXTURES = Path(__file__).parent / "fixtures"
INVALID = [None, 17, "broken", ["unexpected"]]


@pytest.mark.parametrize("suffix", ["json", "jsonl"])
@pytest.mark.parametrize("explicit", [False, True])
def test_mixed_file_preserves_analysis_and_reports_every_rejected_row(tmp_path, suffix, explicit):
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", root)
    original = root / "dataset.jsonl"
    rows = [json.loads(line) for line in original.read_text().splitlines()]
    original.unlink()
    path = root / f"dataset.{suffix}"
    values = rows + INVALID
    path.write_text(json.dumps(values) if suffix == "json" else "\n".join(map(json.dumps, values)))
    extra = ["--dataset", str(path)] if explicit else []
    report, card = _run(root, tmp_path / "out", *extra)
    dataset = report["datasets"][0]
    assert dataset["rows"] == len(rows) == 70
    assert dataset["non_object_rows"] == 4
    assert dataset["non_object_positions"] == [71, 72, 73, 74]
    assert report["areas"]["dataset"]["status"] == "attention"
    assert "4 non-object row(s)" in card
    assert "dataset and scorer all check out" not in card


def test_jsonl_positions_include_blank_physical_lines_and_malformed_control(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text('\n{"input": "ok"}\n\nnull\nbroken json\n17\n')
    raw = audit.load_rows(path)
    assert raw.non_object_rows == 2
    assert raw.non_object_positions == [4, 6]
    assert len(raw.rows) == 1
    assert any("1 line(s) were not valid JSON" in note for note in raw.notes)


def test_rejection_positions_are_bounded_but_count_is_exact(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps([{"input": "ok"}] + [None] * 25))
    raw = audit.load_rows(path)
    assert raw.non_object_rows == 25
    assert raw.non_object_positions == list(range(2, 22))
    assert any("first 20" in note for note in raw.notes)


def test_clean_fixture_and_missing_input_control_still_work(tmp_path):
    clean = audit.load_rows(FIXTURES / "healthy" / "dataset.jsonl")
    assert clean.non_object_rows == 0
    assert clean.non_object_positions == []
    report, card = _run(FIXTURES / "healthy", tmp_path / "out")
    assert report["areas"]["dataset"]["status"] == "ok"
    assert "dataset and scorer all check out" in card
    path = tmp_path / "dataset.json"
    path.write_text('[{"expected_output": "answer"}]')
    dataset = audit.analyse_dataset(path, tmp_path, audit.load_rows(path))
    assert dataset.rows_without_sdk_input == 1
