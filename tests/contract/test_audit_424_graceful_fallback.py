"""Issue #424: the graceful-fallback example must keep the serving incumbent explicit."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.version import Version

DEBUGGING = Path(__file__).resolve().parents[2] / "skills" / "traigent-debugging" / "SKILL.md"


def _section() -> str:
    text = DEBUGGING.read_text(encoding="utf-8")
    return text.split("## Graceful Fallback Pattern", 1)[1].split("## Reference Files", 1)[0]


def test_default_config_is_not_declared_and_ignored() -> None:
    section = _section()
    assert "DEFAULT_CONFIG" not in section
    assert "INCUMBENT_CONFIG" in section
    # every use of the constant beyond its declaration must be a read (set_config and a message)
    assert len(re.findall(r"INCUMBENT_CONFIG", section)) >= 3


def test_search_runs_without_applying_and_restores_the_incumbent() -> None:
    section = _section()
    assert "optimize_sync(apply=False)" in section
    assert "classify.set_config(INCUMBENT_CONFIG)" in section
    assert "using default config" not in section


def test_sdk_supports_apply_false_and_set_config() -> None:
    import inspect

    traigent = pytest.importorskip("traigent")
    if Version(traigent.__version__) < Version("0.30.0"):
        pytest.skip("the example is verified on 0.30.0; apply=False is not asserted below it")
    optimized_function = pytest.importorskip("traigent.core.optimized_function")
    cls = optimized_function.OptimizedFunction
    assert "apply" in inspect.signature(cls.optimize_sync).parameters
    assert callable(cls.set_config) and callable(cls.apply_best_config)
