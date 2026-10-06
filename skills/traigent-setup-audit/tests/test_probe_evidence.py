"""Evidence must survive decoding and remain typed when a report is read later."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tier2_checks as tier2

TESTS = Path(__file__).resolve().parent
AUDIT = TESTS.parent / "scripts" / "audit_project.py"
MARKER = "<<<TRAIGENT_SETUP_AUDIT_RESULT>>>"


@pytest.mark.parametrize(
    "line",
    [
        '{"ran":true,"scores":{"good":[1,1,1,1,1],"partial":[0.5],"bad":[0]},'
        '"errors":[{"case":"good","error_type":"RuntimeError"}],"errors":[]}',
        '{"ran":true,"scores":{"good":[1],"partial":[0.5],"bad":[0]},"errors":[]}',
        '{"ran":true,"scores":{"good":[1,1,1,1,1,1],"partial":[0.5],"bad":[0]},"errors":[]}',
        '{"ran":true,"scores":{"good":[0],"good":[1,1,1,1,1],"partial":[0.5],"bad":[0]},"errors":[]}',
    ],
    ids=["overwritten-errors", "missing-repeats", "excess-repeats", "overwritten-scores"],
)
def test_child_evidence_cannot_forge_all_clear(line: str, tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(TESTS / "fixtures" / "healthy", root)
    (root / "scorer.py").write_text(
        "import os\nimport sys\n"
        f"sys.stdout.write({(MARKER + line + chr(10))!r})\n"
        "sys.stdout.flush()\nos._exit(0)\n"
        "def score(output, expected):\n    return 1.0\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, str(AUDIT), "--root", str(root), "--json", str(out), "--repeats", "5"],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["scorer_probe"]["ran"] is False
    assert report["scorer_probe"]["stage"] == "tampered-result"
    assert report["areas"]["scorer"]["status"] != "ok"
    assert report["next_step"]["branch"] != "g"


@pytest.mark.parametrize("how", ["string-ran", "bool-scores", "missing-repeats", "bool-repeats", "null-repeats"])
def test_stored_evidence_cannot_forge_all_clear(how: str, healthy_tier1: Path, tmp_path: Path) -> None:
    report = json.loads(healthy_tier1.read_text(encoding="utf-8"))
    assert report["next_step"]["branch"] == "g"
    probe = report["scorer_probe"]
    if how == "string-ran":
        probe["ran"] = "false"
    elif how == "bool-scores":
        probe["scores"]["good"] = [True] * 5
        probe["scores"]["bad"] = [False]
    elif how == "null-repeats":
        probe["requested_repeats"] = None
    elif how == "bool-repeats":
        probe["requested_repeats"] = True
    else:
        probe["requested_repeats"] = 5
        probe["scores"]["good"] = [1]
    out = tmp_path / "stored.json"
    out.write_text(json.dumps(report), encoding="utf-8")
    loaded = tier2.load_tier1(out)
    assert loaded.probe_verdict == "not-run"
    assert loaded.stale_all_clear
    result = subprocess.run(
        [sys.executable, str(TESTS.parent / "scripts" / "tier2_checks.py"), "--from-audit", str(out)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "APPROVAL CARD — stop-here   (recommended)" in result.stdout
    assert "APPROVAL CARD — plan   (recommended)" not in result.stdout


@pytest.mark.parametrize("member", ["errors", "scores"])
def test_stored_duplicate_members_are_refused(member: str, healthy_tier1: Path, tmp_path: Path) -> None:
    report = json.loads(healthy_tier1.read_text(encoding="utf-8"))
    original = json.dumps(report["scorer_probe"])
    hidden = '"errors":[{"case":"good","error_type":"RuntimeError"}],' if member == "errors" else '"scores":{"good":[0]},'
    replacement = "{" + hidden + original[1:]
    text = json.dumps(report)
    assert text.count(original) == 1
    out = tmp_path / "duplicate.json"
    out.write_text(text.replace(original, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match="could not be read as JSON"):
        tier2.load_tier1(out)
    result = subprocess.run(
        [sys.executable, str(TESTS.parent / "scripts" / "tier2_checks.py"), "--from-audit", str(out)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode != 0
    assert "could not be read as JSON" in result.stderr
    assert "Traceback" not in result.stderr
    assert "(recommended)" not in result.stdout


def test_requested_repeat_count_survives_report_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, str(AUDIT), "--root", str(TESTS / "fixtures" / "healthy"),
         "--json", str(out), "--repeats", "3"],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["scorer_probe"]["requested_repeats"] == 3
    assert len(report["scorer_probe"]["scores"]["good"]) == 3
    assert report["next_step"]["branch"] == "g"
    assert tier2.load_tier1(out).probe_verdict == "repeatable"
    # Earlier writers did not retain the requested count. Do not invent one.
    del report["scorer_probe"]["requested_repeats"]
    out.write_text(json.dumps(report), encoding="utf-8")
    assert tier2.load_tier1(out).probe_verdict == "repeatable"
