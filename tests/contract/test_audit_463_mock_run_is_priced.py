"""Issue #463: on SDK 0.31.0+ a mock run is still priced and gated.

The skills said the mock dry run is "zero cost" and that mock mode "skips the pre-run
pricing estimate". Since SDK 0.31.0 neither holds: the estimate runs and a realistic
dataset is refused with ``CostLimitExceeded`` before trial 1. The supported routes are a
small slice or ``TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT=1`` with an explicit non-production
environment; ``TRAIGENT_COST_APPROVED`` is the wrong answer for a mock run.

Text lints pin the corrected wording; the probe pins the SDK behaviour the wording
describes (0.31.0+ only, where the behaviour exists).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.version import Version

from .mock_probe import run_probe

CARD = "docs/shared/run-cost-and-limits.v1.md"
RETIRED = {
    "Mock mode skips only the pre-run pricing estimate": "false on SDK 0.31.0+",
    "Dry run for $0": "the card's guard 1 must not promise $0 without the estimate caveat",
}
CARRIERS = (
    "skills/traigent-boost-agent",
    "skills/traigent-optimize-run",
    "skills/traigent-setup-quickstart",
)


def _markdown(root: Path) -> list[Path]:
    return sorted(
        [*(root / "skills").rglob("*.md"), *(root / "docs" / "shared").glob("*.md")]
    )


def test_retired_mock_cost_claims_do_not_return(repo_root: Path) -> None:
    offenders = [
        f"{path.relative_to(repo_root)}: {phrase!r} ({why})"
        for path in _markdown(repo_root)
        for phrase, why in RETIRED.items()
        if phrase in path.read_text(encoding="utf-8")
    ]
    assert not offenders, "\n".join(offenders)


def test_boost_agent_step_three_is_not_called_zero_cost(repo_root: Path) -> None:
    text = (repo_root / "skills/traigent-boost-agent/SKILL.md").read_text(encoding="utf-8")
    assert "end-to-end at zero cost" not in text
    step3 = text.split("### Step 3: Run Mock Optimization", 1)[1].split("### Step 3.5", 1)[0]
    flat = " ".join(step3.split())
    assert "still priced and gated" in flat
    assert "small slice" in flat
    assert "TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT=1" in flat
    assert "non-production" in flat
    assert "Never set `TRAIGENT_COST_APPROVED=true`" in flat


def test_shared_card_names_the_mock_estimate_and_both_routes(repo_root: Path) -> None:
    text = " ".join((repo_root / CARD).read_text(encoding="utf-8").split())
    section = text.split("## Mock dry runs on SDK 0.31.0+", 1)[1].split("## Before a real run", 1)[0]
    assert "CostLimitExceeded" in section
    assert "small slice" in section.lower()
    assert "TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT=1" in section
    assert "`ci`" in section, "the exemption is ignored for ci; the card must say so"
    assert "Do not set `TRAIGENT_COST_APPROVED=true`" in section
    guard1 = text.split("1. **Dry run with no provider spend.**", 1)[1].split("2. **A spending cap.**", 1)[0]
    assert "still apply to a mock run on SDK 0.31.0+" in guard1


@pytest.mark.parametrize("carrier", CARRIERS)
def test_card_copies_carry_the_mock_section(repo_root: Path, carrier: str) -> None:
    copy = (repo_root / carrier / "references/run-cost-and-limits.md").read_text(encoding="utf-8")
    assert "## Mock dry runs on SDK 0.31.0+" in copy


def test_exempt_env_var_is_prose_versioned_everywhere(repo_root: Path) -> None:
    """Every skill file naming the variable states the 0.31.0 requirement beside it."""
    missing = []
    for path in _markdown(repo_root):
        if "docs/shared" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT", text):
            window = text[max(0, match.start() - 1500) : match.end() + 1500]
            if "0.31" not in window:
                missing.append(f"{path.relative_to(repo_root)}@{match.start()}")
    assert not missing, missing


# --- SDK behaviour the wording describes (0.31.0+) -------------------------------


def _needs_0_31(sdk_version_label: str) -> None:
    if sdk_version_label != "develop" and Version(sdk_version_label) < Version("0.31.0"):
        pytest.skip("mock runs are priced and gated from SDK 0.31.0")


def test_large_mock_run_is_refused_and_a_small_slice_runs(
    tmp_path: Path, sdk_version_label: str
) -> None:
    _needs_0_31(sdk_version_label)
    assert run_probe(tmp_path / "big", rows=60, scorer="number", extra_env={}) == {
        "error": "CostLimitExceeded"
    }
    small = run_probe(tmp_path / "small", rows=3, scorer="number", extra_env={})
    assert small["error"] is None and small["trials"] == 2 and small["failed"] == 0


@pytest.mark.parametrize(
    ("env", "refused"),
    [
        ({"TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT": "1", "ENVIRONMENT": "development"}, False),
        ({"TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT": "1", "ENVIRONMENT": "ci"}, True),
        ({"TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT": "1", "ENVIRONMENT": None}, True),
        ({"ENVIRONMENT": "development"}, True),
    ],
    ids=["exempt+development", "exempt+ci", "exempt+unset-env", "development-only"],
)
def test_exemption_needs_the_variable_and_a_non_production_environment(
    tmp_path: Path, sdk_version_label: str, env: dict, refused: bool
) -> None:
    _needs_0_31(sdk_version_label)
    data = run_probe(tmp_path, rows=60, scorer="number", extra_env=env)
    if refused:
        assert data == {"error": "CostLimitExceeded"}
    else:
        assert data["error"] is None and data["trials"] == 2 and data["failed"] == 0
