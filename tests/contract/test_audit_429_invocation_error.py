"""Issue #429: ``InvocationError`` does not catch ordinary per-example failures."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

DEBUGGING = Path(__file__).resolve().parents[2] / "skills" / "traigent-debugging"


def test_docs_do_not_claim_every_function_exception_is_an_invocation_error() -> None:
    skill = (DEBUGGING / "SKILL.md").read_text(encoding="utf-8")
    ref = (DEBUGGING / "references" / "error-reference.md").read_text(encoding="utf-8")
    assert "The decorated function raised an exception during a trial." not in skill
    assert "**Function raised an exception during a trial.**" not in ref
    assert "Function call failed:" in skill
    assert "propagate as their own type" not in skill
    assert "catches a generic exception from a trial" in skill
    assert "scored-example coverage" in skill and "scored-example coverage" in ref
    assert "print(f\"Original error: {e.original_error}\")" not in skill


def test_sdk_turns_ordinary_exceptions_into_per_example_failures() -> None:
    base = pytest.importorskip("traigent.evaluators.base")
    source = inspect.getsource(base)
    assert 'error_msg = f"Function call failed: {e}"' in source
    assert "except (FriendlyTraigentError, CoreTraigentError):\n            raise" in source
