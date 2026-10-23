"""Issue #417: metric-function judge calls are not unconditionally unmetered."""

from __future__ import annotations

from pathlib import Path

import pytest
from packaging.version import Version

SKILLS = Path(__file__).resolve().parents[2] / "skills"
CHOOSE = SKILLS / "traigent-eval-choose-metric" / "SKILL.md"
BUILD = SKILLS / "traigent-eval-build" / "SKILL.md"


def test_no_unconditional_unmetered_claim() -> None:
    choose = " ".join(CHOOSE.read_text(encoding="utf-8").split())
    build = BUILD.read_text(encoding="utf-8")
    assert "does not see judge calls made inside a metric function" not in choose
    assert "is **not** in the SDK's cost ledger" not in build
    assert "captur" in choose
    assert "0.30.0" in choose
    assert "depends on the SDK version and on capture" in build
    assert "not provider enforcement" in build
    assert "concurrent trials are still" not in build
    assert "ContextVar" in build
    assert "Budget judge calls as their own line" in build


def test_sdk_folds_captured_metric_function_cost() -> None:
    traigent = pytest.importorskip("traigent")
    if Version(traigent.__version__) < Version("0.30.0"):
        pytest.skip("captured judge cost is folded into recorded cost from 0.30.0")
    langchain = pytest.importorskip("traigent.utils.langchain_interceptor")
    assert hasattr(langchain, "_capture_scope")
    local = pytest.importorskip("traigent.evaluators.local")
    assert hasattr(local.LocalEvaluator, "_fold_metric_function_llm_cost")
