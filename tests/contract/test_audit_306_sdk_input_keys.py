"""The setup audit flags every committed fixture dataset the SDK refuses to load.

The audit discovers candidate datasets through a wider set of input-like keys
than the SDK accepts, so a file can look like a dataset to the audit and still
fail on the first `eval_dataset=` load. This loads each fixture file with the
installed SDK's own loader and checks that every file it rejects carries an
audit finding naming `eval_dataset`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from traigent.evaluators.base import Dataset
from traigent.utils.exceptions import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "traigent-setup-audit"
FIXTURES = SKILL_DIR / "tests" / "fixtures"


def _audit_module():
    scripts = str(SKILL_DIR / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("audit_project")


def _sdk_rejects(path: Path) -> bool:
    try:
        Dataset.from_jsonl(str(path))
    except ValidationError:
        return True
    return False


def test_every_fixture_dataset_the_sdk_rejects_is_flagged_by_the_audit() -> None:
    audit = _audit_module()
    files = sorted(
        path
        for path in FIXTURES.rglob("*.jsonl")
        if "traigent-runs" not in path.relative_to(FIXTURES).parts
    )
    rejected = [path for path in files if _sdk_rejects(path)]
    # Teeth: the bank holds at least one file the SDK refuses, so an empty
    # loop cannot pass this test vacuously.
    assert rejected, "no fixture dataset is rejected by the SDK loader"

    unflagged = []
    for path in rejected:
        reports, _, _, _ = audit.scan_datasets([path], path.parent)
        findings = [finding for report in reports for finding in report.findings]
        if not any("eval_dataset" in finding for finding in findings):
            unflagged.append(str(path.relative_to(FIXTURES)))
    assert unflagged == []


def test_every_fixture_dataset_the_sdk_loads_has_no_input_key_finding() -> None:
    audit = _audit_module()
    for path in sorted(FIXTURES.rglob("*.jsonl")):
        if "traigent-runs" in path.relative_to(FIXTURES).parts or _sdk_rejects(path):
            continue
        reports, _, _, _ = audit.scan_datasets([path], path.parent)
        for report in reports:
            assert not any("eval_dataset" in f for f in report.findings), path
