"""Issue #429: ``InvocationError`` does not catch ordinary per-example failures."""

from __future__ import annotations

import asyncio
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

    # Behaviour, not source text: the conversion site moved between SDK releases (develop
    # builds it through function_call_failure_text), so run a raising function through the
    # public LocalEvaluator and check the per-example failure carries the marker text.
    # Released 0.32.0/0.33.0 print "Function call failed: boom-marker-429"; develop prints
    # "Function call failed: RuntimeError: boom-marker-429". Both substrings must be present.
    from traigent.evaluators.local import LocalEvaluator

    def raising_function(question):
        raise RuntimeError("boom-marker-429")

    evaluator = LocalEvaluator(metrics=["accuracy"], detailed=True)
    dataset = base.Dataset(
        examples=[base.EvaluationExample(input_data={"question": "q"}, expected_output="a")]
    )
    result = asyncio.run(evaluator.evaluate(raising_function, {}, dataset))
    failures = [r for r in result.example_results if not r.success]
    assert len(failures) == 1, result.example_results
    message = failures[0].error_message or ""
    assert "Function call failed:" in message, message
    assert "boom-marker-429" in message, message

    # The SDK's own errors still propagate instead of becoming per-example failures.
    source = inspect.getsource(base)
    assert "except (FriendlyTraigentError, CoreTraigentError):\n            raise" in source
