"""Issue #447: four reference claims that were false on the published SDK.

A. ``ProviderValidationError`` was described as raised automatically. The SDK
   never raises it -- provider validation is opt-in.
B. ``TRAIGENT_STRICT_COST_ACCOUNTING`` was given the wrong meaning (a budget
   guard). It is a fail-fast for unmeasurable call cost.
C. A row's own ``metadata`` object was described as nested. It is **merged**
   from 0.28.0, and on a key collision the nested value silently wins.
D. ``traigent models --check`` was said to "catch typos". Keyless, it accepts a
   misspelling that follows a known prefix.

The behaviour assertions run against the installed SDK; the text assertions pin
the corrected wording so it cannot drift back.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .test_audit_349_fenced_blocks import skip_unless_current_released_sdk

ROOT = Path(__file__).resolve().parents[2]

DEBUGGING = ROOT / "skills" / "traigent-debugging" / "SKILL.md"
ERROR_REF = ROOT / "skills" / "traigent-debugging" / "references" / "error-reference.md"
ENV_VARS = (
    ROOT / "skills" / "traigent-setup-quickstart" / "references" / "environment-variables.md"
)
COST_MGMT = (
    ROOT / "skills" / "traigent-optimize-run" / "references" / "cost-management.md"
)
METADATA_PAGES = (
    ROOT / "skills" / "traigent-eval-build" / "SKILL.md",
    ROOT / "skills" / "traigent-dataset-curate" / "SKILL.md",
    ROOT / "skills" / "traigent-recipe-text2sql" / "SKILL.md",
)
TYPO_PAGES = (
    ROOT / "skills" / "traigent-setup-quickstart" / "SKILL.md",
    ROOT / "skills" / "traigent-setup-integrations" / "SKILL.md",
    ROOT / "skills" / "traigent-setup-integrations" / "references" / "litellm.md",
    DEBUGGING,
)


def _sdk_package_root() -> Path:
    traigent = pytest.importorskip("traigent")
    return Path(traigent.__file__).resolve().parent


def _sdk_sources() -> list[Path]:
    root = _sdk_package_root()
    # The wheel bundles a copy of the skills; those are documents, not SDK code.
    return [p for p in sorted(root.rglob("*.py")) if "/skills/" not in p.as_posix()]


# --------------------------------------------------------------------------- A


def test_a_sdk_never_raises_provider_validation_error(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the #447 claims")
    # Parse rather than grep: the SDK's own docstrings describe the exception
    # ("caller may raise ProviderValidationError"), which is prose, not a raise.
    raisers: list[str] = []
    for path in _sdk_sources():
        if "ProviderValidationError" not in path.read_text(encoding="utf-8"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken wheel is its own problem
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = exc.id if isinstance(exc, ast.Name) else getattr(exc, "attr", None)
            if name == "ProviderValidationError":
                raisers.append(f"{path}:{node.lineno}")
    assert not raisers, (
        "the SDK now raises ProviderValidationError somewhere -- the skills say it "
        f"never does; restate the claim: {raisers}"
    )


def test_a_docs_state_the_exception_is_opt_in() -> None:
    debugging = DEBUGGING.read_text(encoding="utf-8")
    assert "never by the SDK on its own" in debugging
    assert "API key validation fails before optimization starts" not in debugging
    error_ref = ERROR_REF.read_text(encoding="utf-8")
    assert "never raised by the SDK on its own" in error_ref
    assert "Raised before optimization starts when provider API keys" not in error_ref
    # boost-agent is the front door and carried the same claim; the first pass
    # corrected two files and left the one most readers open first.
    for path in sorted(ROOT.glob("skills/**/*.md")):
        if "/tests/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        assert "auto-validates them before starting" not in text, path.relative_to(ROOT)
        assert "Traigent auto-validates" not in text, path.relative_to(ROOT)


# --------------------------------------------------------------------------- B


def test_b_strict_cost_accounting_is_a_fail_fast_not_a_budget_guard() -> None:
    env_vars = ENV_VARS.read_text(encoding="utf-8")
    row = next(
        line
        for line in env_vars.splitlines()
        if line.startswith("| `TRAIGENT_STRICT_COST_ACCOUNTING`")
    )
    assert "Cost overruns raise errors instead of warnings" not in row
    assert "CostTrackingRequiredError" in row
    assert "TRAIGENT_RUN_COST_LIMIT" in row, (
        "the row must point budget overruns at the variable that governs them"
    )


def test_b_sibling_pages_agree(sync_map: dict, sdk_version_label: str) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the #447 claims")
    cost_enforcement = _sdk_package_root() / "core" / "cost_enforcement.py"
    assert "Fail fast for unknown/missing runtime costs" in cost_enforcement.read_text(
        encoding="utf-8"
    )
    assert "CostTrackingRequiredError" in COST_MGMT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- C


def test_c_row_metadata_is_merged_on_the_released_sdk(
    tmp_path: Path, sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the #447 claims")
    from traigent.evaluators.base import Dataset

    row = {
        "input": {"q": "a"},
        "output": "b",
        "db_id": "x",
        "metadata": {"db_id": "y", "k": 1},
    }
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    previous = os.environ.get("TRAIGENT_DATASET_ROOT")
    os.environ["TRAIGENT_DATASET_ROOT"] = str(tmp_path)
    try:
        example = Dataset.from_jsonl(str(path)).examples[0]
    finally:
        if previous is None:
            os.environ.pop("TRAIGENT_DATASET_ROOT", None)
        else:
            os.environ["TRAIGENT_DATASET_ROOT"] = previous
    assert "metadata" not in example.metadata, (
        "the row's metadata is nested again; the skills say it is merged from 0.28.0"
    )
    assert example.metadata["db_id"] == "y", (
        "the nested value no longer wins the collision the skills warn about"
    )


def test_c_docs_version_scope_the_metadata_shape() -> None:
    for path in METADATA_PAGES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        assert "0.28.0" in text, f"{rel}: the metadata shape must name its boundary"
        assert "0.24.0-0.27.0" in text, f"{rel}: the older shape must stay named"
        assert "merged" in text, f"{rel}: the >=0.28.0 shape is a merge"


# --------------------------------------------------------------------------- D


def _models_check(model: str) -> tuple[int, dict]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENAI_", "ANTHROPIC_", "TRAIGENT_"))
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "traigent.cli.main",
            "models",
            "--provider",
            "openai",
            "--check",
            model,
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:  # pragma: no cover - surfaced in the assertion
        payload = {"_stdout": proc.stdout, "_stderr": proc.stderr}
    return proc.returncode, payload


def test_d_models_check_accepts_a_typo_after_a_known_prefix(
    sync_map: dict, sdk_version_label: str
) -> None:
    skip_unless_current_released_sdk(sync_map, sdk_version_label, "the #447 claims")
    _code, typo = _models_check("gpt-4o-mnii")
    assert typo.get("valid") is True, (
        "`traigent models --check` now rejects a misspelling after a known prefix; "
        f"the skills say keyless it does not -- restate the claim: {typo}"
    )
    _code, unknown_prefix = _models_check("gtp-4o")
    assert unknown_prefix.get("valid") is False, unknown_prefix


def test_d_docs_do_not_overclaim_the_typo_check() -> None:
    for path in TYPO_PAGES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        assert "gpt-4o-mnii" in text, (
            f"{rel}: name the misspelling the check accepts, so the limit is concrete"
        )
        assert "catches typos and unknown ID shapes" not in text, rel
        assert "catch typos and unknown ID shapes" not in text, rel
