"""Contract tests for the shared run-cost card (docs/shared/run-cost-and-limits.v1.md).

Pinned here:

1. **One source, byte-identical copies, reachable from a single-skill install.** The card is
   authored once in docs/shared/ and shipped as generated copies by
   tools/contract/sync_run_cost_reference.py, exactly like the economics reference
   (tests/contract/test_economics_reference.py).

2. **Version-neutral content only.** The card ships before SDK 0.30.0, so it must not teach the
   unmeasured-cost trial-limit rules that exist only on SDK develop (the 10-trial safety stop,
   explicit max_trials consent, COST_UNMEASURED_* warning codes) or raw-OpenAI capture.

3. **The corrected statements do not come back.** The call-count formula that ignored calls
   per example and judge calls, and the "tracks everything / works with every provider" claims.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


CANONICAL_RELPATH = "docs/shared/run-cost-and-limits.v1.md"
REFERENCE_RELPATH = "references/run-cost-and-limits.md"
POINTER_MARKER = "`references/run-cost-and-limits.md`"

# The owner-approved homes of the card. Discovery is by pointer marker; this set pins that the
# primary home and both first-paid-run entry points keep carrying it.
EXPECTED_CARRIERS = {
    "traigent-optimize-run",
    "traigent-boost-agent",
    "traigent-setup-quickstart",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _carrier_dirs(root: Path) -> list[Path]:
    return [
        d
        for d in sorted((root / "skills").iterdir())
        if d.is_dir()
        and (d / "SKILL.md").is_file()
        and POINTER_MARKER in (d / "SKILL.md").read_text(encoding="utf-8")
    ]


CARRIERS = _carrier_dirs(_repo_root())
CARRIER_IDS = [d.name for d in CARRIERS]


def _canonical_text() -> str:
    return (_repo_root() / CANONICAL_RELPATH).read_text(encoding="utf-8")


def test_expected_skills_carry_the_card() -> None:
    assert EXPECTED_CARRIERS <= set(CARRIER_IDS), (
        f"missing run-cost card pointer in: {sorted(EXPECTED_CARRIERS - set(CARRIER_IDS))}. "
        f"Each must mention {POINTER_MARKER} in SKILL.md."
    )


@pytest.mark.parametrize("skill_dir", CARRIERS, ids=CARRIER_IDS)
def test_shipped_card_is_byte_identical_to_canonical(skill_dir: Path) -> None:
    shipped = skill_dir / REFERENCE_RELPATH
    assert shipped.is_file(), (
        f"{skill_dir.name}: SKILL.md points at {REFERENCE_RELPATH} but it is not shipped — "
        "run: python tools/contract/sync_run_cost_reference.py"
    )
    assert shipped.read_bytes() == (_repo_root() / CANONICAL_RELPATH).read_bytes(), (
        f"{skill_dir.name}: {REFERENCE_RELPATH} drifted from {CANONICAL_RELPATH}. Edit the "
        "canonical file, then run: python tools/contract/sync_run_cost_reference.py"
    )


@pytest.mark.parametrize("skill_dir", CARRIERS, ids=CARRIER_IDS)
def test_single_skill_install_can_read_the_card(skill_dir: Path, tmp_path: Path) -> None:
    installed = tmp_path / ".agents" / "skills" / skill_dir.name
    installed.parent.mkdir(parents=True)
    shutil.copytree(skill_dir, installed)
    reference = installed / REFERENCE_RELPATH
    assert reference.is_file(), (
        f"{skill_dir.name}: a single-skill install has no {REFERENCE_RELPATH}"
    )
    text = reference.read_text(encoding="utf-8")
    assert "What a Run Costs, and How to Keep It Safe" in text


def test_sync_tool_check_mode_passes() -> None:
    result = subprocess.run(
        [sys.executable, "tools/contract/sync_run_cost_reference.py", "--check"],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"sync_run_cost_reference.py --check failed:\n{result.stdout}\n{result.stderr}"
    )


def test_sync_tool_detects_a_tampered_copy(tmp_path: Path) -> None:
    """Guard the guard: --check must fail on drift, not pass vacuously."""
    repo_copy = tmp_path / "repo"
    shutil.copytree(
        _repo_root(),
        repo_copy,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", ".bucket-*", "__pycache__", ".pytest_cache"
        ),
    )
    tampered = repo_copy / "skills" / CARRIERS[0].name / REFERENCE_RELPATH
    tampered.write_text("locally edited generated artifact\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "tools/contract/sync_run_cost_reference.py", "--check"],
        cwd=repo_copy,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, "--check passed on a tampered copy"


# Rules that exist only on SDK develop (0.30.0.dev) — deferred until 0.30.0 is released.
DEFERRED_UNRELEASED_PATTERNS = (
    r"COST_UNMEASURED_",
    r"TRAIGENT_FALLBACK_TRIAL_LIMIT",
    r"\b10-trial",  # "10-trial safety stop"; the worked example's "10 trials × ..." is fine
    r"(?:stops?|stopped) after \*?\*?10 trials",
    r"llm_usage_measured",
    r"enable_openai_optimization",
    r"OpenAI override",
)


def test_card_teaches_no_unreleased_sdk_behaviour() -> None:
    text = _canonical_text()
    hits = [p for p in DEFERRED_UNRELEASED_PATTERNS if re.search(p, text)]
    assert not hits, (
        f"{CANONICAL_RELPATH} teaches behaviour not in any released SDK: {hits}. The "
        "unmeasured-cost trial-limit rules wait for SDK 0.30.0."
    )


def test_card_states_the_cost_drivers_and_the_measured_only_cap() -> None:
    text = re.sub(r"\s+", " ", _canonical_text())
    for required in (
        "trials × examples × model calls per example",
        "LLM judge",
        "illustrative — use your model's real price",
        "`cost_limit` only bounds the cost Traigent measures",
        "`max_total_examples`",
        "`enable_mock_mode_for_quickstart()`",
        "`offline=True`",
        "`results.total_cost` above 0",
    ):
        assert required in text, f"{CANONICAL_RELPATH} lost required statement {required!r}"
    # max_samples is a backend field / stop reason, never a user argument.
    assert "max_samples" not in text


# Statements this change corrected. They must not reappear in any shipped skill markdown.
CORRECTED_STATEMENTS = (
    r"`max_trials x dataset_size` \(upper bound\)",
    r"upper bound is \(max_trials x dataset_size\)",
    r"works automatically with all LiteLLM-supported providers",
    r"tracks LLM API costs in real time",
    r"provides real-time cost tracking",
)


def test_corrected_cost_statements_do_not_return() -> None:
    offenders = []
    for path in sorted((_repo_root() / "skills").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern in CORRECTED_STATEMENTS:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(_repo_root())}: {pattern}")
    assert not offenders, "corrected cost statements came back:\n" + "\n".join(offenders)
