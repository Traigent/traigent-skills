"""Unsupported knob evidence and bounded sibling reads cannot certify all-clear."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import audit_project as audit
from conftest import FIXTURES, run_tier2
from tier2_fake_backend import RUN_ID


@pytest.mark.parametrize("status", [None, "unknown", False, [], {}])
@pytest.mark.parametrize("run_id", [None, RUN_ID])
def test_unknown_stored_knob_status_refuses_all_clear(
    healthy_tier1: Path, tmp_path: Path, status: object, run_id: str | None,
) -> None:
    report = json.loads(healthy_tier1.read_text())
    assert report["next_step"]["branch"] == "g"
    report["entry_points"][0]["knobs"][0]["status"] = status
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(report))
    argv = ["--from-audit", str(path)]
    if run_id:
        argv += ["--run-id", run_id]
    done = run_tier2(*argv)
    assert done.returncode == 0, done.stderr
    assert "APPROVAL CARD — stop-here   (recommended)" in done.stdout
    assert done.stdout.count("(recommended)") == 1
    assert "Agent area" in done.stdout
    assert "stored entry points could not be read" in done.stdout


def test_explicit_sibling_cap_reports_incomplete_dataset(
    tmp_path: Path, monkeypatch,
) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURES / "healthy", project)
    rows = [json.loads(line) for line in (project / "dataset.jsonl").read_text().splitlines()]
    (project / "dataset.jsonl").unlink()
    for name, split in [("tuning.jsonl", "tune"), ("holdout-a.jsonl", "holdout")]:
        selected = [{k: v for k, v in row.items() if k != "metadata"}
                    for row in rows if row["metadata"]["split"] == split]
        (project / name).write_text("".join(json.dumps(row) + "\n" for row in selected))
    (project / "holdout-z.jsonl").write_text("{broken JSON\n")
    monkeypatch.setattr(audit, "MAX_DATA_FILES", 2)
    args = audit.parse_args(["--root", str(project), "--dataset", str(project / "tuning.jsonl")])
    report = audit.build_report(project, args, "active")
    assert report["files"]["dataset_candidates"] == 3
    assert len(report["datasets"]) == 2
    assert report["areas"]["dataset"]["status"] == "attention"
    assert report["next_step"]["branch"] == "f"
    assert "2 of 3" in report["next_step"]["line"]
    assert "not analysed" in report["next_step"]["line"]
