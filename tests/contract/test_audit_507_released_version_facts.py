"""Issues #488 and #507 (members #487, #491, #492): released-version facts.

- #488: ``docs/version-matrix.md`` carries the SDK 0.32.0 honest cost-totals row,
  and the cost reference points at it, so the 0.32.0 behaviour is recorded once.
- #507 / #487: the Python floor the quickstart and README state for the SDK is
  the ``Requires-Python`` of the released wheel that the bucket installed. The
  floor is read from the installed distribution metadata, never hardcoded here.

The Python-floor check runs only in a bucket whose installed SDK is at or above
the release the stated claims name (0.32.0); in older buckets it skips with that
reason, because the claims describe that release.
"""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .test_version_matrix import MATRIX_RELPATH, _parse_matrix, _pointer_sites

ROOT = Path(__file__).resolve().parents[2]

COST_ROW = "cost-totals"
COST_REFERENCE = (
    ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md"
)
CLAIM_RELEASE = Version("0.32.0")

# Each claim is the exact customer-facing sentence that states the SDK floor.
# The regex captures the stated floor; a missing or reworded claim fails the
# test, so the check cannot pass vacuously.
PYTHON_FLOOR_CLAIMS = (
    (
        ROOT / "skills" / "traigent-setup-quickstart" / "SKILL.md",
        re.compile(r"Python >= (?P<floor>\d+\.\d+) \(SDK 0\.32\.0\+"),
    ),
    (
        ROOT
        / "skills"
        / "traigent-setup-quickstart"
        / "references"
        / "installation-extras.md",
        re.compile(r"Requires Python >= (?P<floor>\d+\.\d+) \(SDK 0\.32\.0\+"),
    ),
    (
        ROOT / "README.md",
        re.compile(r"Python (?P<floor>\d+\.\d+)[–-]\d+\.\d+ \(SDK 0\.32\.0\+"),
    ),
)


def test_cost_totals_row_names_0_32_0_and_its_reference_points_at_it() -> None:
    rows = {row.fact_id: row for row in _parse_matrix(ROOT)}
    row = rows.get(COST_ROW)
    assert row is not None, (
        f"{MATRIX_RELPATH}: no `{COST_ROW}` row for the SDK 0.32.0 honest cost "
        "totals (#488)"
    )
    assert row.changed_in_version == "0.32.0", row.changed_in_version
    assert row.issue_ref == "Traigent/Traigent#2688", row.issue_ref
    pointed_from = {
        path for path, _, fact_id in _pointer_sites(ROOT) if fact_id == COST_ROW
    }
    assert COST_REFERENCE in pointed_from, (
        f"{COST_REFERENCE.relative_to(ROOT)} must carry a "
        f"`see version-matrix: {COST_ROW}` pointer next to its SDK 0.32.0 "
        "cost-total statement"
    )


def _installed_release_python_floor() -> Version:
    requires = importlib.metadata.metadata("traigent")["Requires-Python"]
    assert requires, "installed traigent distribution declares no Requires-Python"
    lower_bounds = [
        Version(spec.version)
        for spec in SpecifierSet(requires)
        if spec.operator in (">=", "==", "~=")
    ]
    assert lower_bounds, f"no lower bound in Requires-Python {requires!r}"
    return max(lower_bounds)


def test_stated_python_floor_equals_the_released_sdk_requires_python(
    sdk_version_label: str,
) -> None:
    if sdk_version_label in ("develop", "unknown") or (
        Version(sdk_version_label) < CLAIM_RELEASE
    ):
        pytest.skip(
            f"the stated Python floor describes SDK {CLAIM_RELEASE}; this bucket "
            f"is {sdk_version_label}"
        )
    installed = importlib.metadata.version("traigent")
    assert installed == sdk_version_label, (installed, sdk_version_label)
    released_floor = _installed_release_python_floor()

    mismatches: list[str] = []
    for path, pattern in PYTHON_FLOOR_CLAIMS:
        rel = path.relative_to(ROOT)
        found = list(pattern.finditer(path.read_text(encoding="utf-8")))
        assert len(found) == 1, (
            f"{rel}: expected exactly one Python floor claim for SDK 0.32.0+, "
            f"found {len(found)}"
        )
        stated = Version(found[0].group("floor"))
        if stated != released_floor:
            mismatches.append(
                f"{rel}: states Python >= {stated} for SDK 0.32.0+, but traigent "
                f"{installed} Requires-Python is >= {released_floor}"
            )
    assert not mismatches, "\n".join(mismatches)
