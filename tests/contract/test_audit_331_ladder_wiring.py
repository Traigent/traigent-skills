"""Issue #331: every tier of the wire-first ladder must be wireable, or say it is not.

The Tier 5 ``BaseEvaluator`` example could not be plugged into
``@traigent.optimize``: ``EvaluationOptions(custom_evaluator=<instance>)`` fails
``Input should be callable``, the class fails the ``(func, config, example)``
signature check, and ``evaluator=`` accepts only an external-service evaluator.

Gates: each ``### Tier N`` section's first python block must execute and
decorate a function with ``@traigent.optimize`` without error, unless the ladder
row marks the tier "not wireable" and the section ships no code. The last test
pins the SDK behavior behind "not wireable": when a release starts accepting a
``BaseEvaluator``, it goes red so the note is revisited.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .test_audit_326_comparator_case import FENCE_RE, _run_driver

EVAL_BUILD = (
    Path(__file__).resolve().parents[2] / "skills" / "traigent-eval-build" / "SKILL.md"
)
TEXT = EVAL_BUILD.read_text(encoding="utf-8")
TIER_SECTIONS = dict(
    re.findall(r"^### Tier (\d+):[^\n]*\n(.*?)(?=^##)", TEXT, re.MULTILINE | re.DOTALL)
)
LADDER_ROWS = dict(re.findall(r"^\| (\d) \| (.*)$", TEXT, re.MULTILINE))

DECORATE_BODY = """
write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
write_rows("extraction.jsonl", [{"input": {"text": "t"}, "output": {"label": "a"}}])
import traigent
ns = load_block(sys.argv[1])
decorated = [name for name, value in ns.items() if callable(getattr(value, "optimize_sync", None))]
emit(decorated)
"""


def test_ladder_has_tiers_one_to_five() -> None:
    assert sorted(LADDER_ROWS) == ["1", "2", "3", "4", "5"], LADDER_ROWS


@pytest.mark.parametrize("tier", ["2", "3", "4", "5"])
def test_tier_example_wires_or_is_marked_not_wireable(
    tier: str, tmp_path: Path
) -> None:
    section = TIER_SECTIONS.get(tier)
    assert section is not None, f"missing '### Tier {tier}' section"
    blocks = FENCE_RE.findall(section)
    if "not wireable" in LADDER_ROWS[tier]:
        assert not blocks, f"Tier {tier} is marked not wireable but still ships code"
        return
    assert blocks, f"Tier {tier} has no example"
    decorated = _run_driver(tmp_path, blocks[0], DECORATE_BODY)
    assert decorated, (
        f"Tier {tier} example does not decorate a function with @traigent.optimize"
    )


def test_sdk_still_rejects_a_base_evaluator(tmp_path: Path) -> None:
    body = """
    import traigent
    from traigent.api.decorators import EvaluationOptions
    from traigent.evaluators import BaseEvaluator

    class Probe(BaseEvaluator):
        async def evaluate(self, func, config, dataset, **kwargs):
            raise NotImplementedError

    write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
    outcome = {}
    for label, value in (("instance", Probe()), ("class", Probe)):
        try:
            options = EvaluationOptions(eval_dataset=str(Path("eval/qa.jsonl").resolve()), custom_evaluator=value)

            @traigent.optimize(evaluation=options, objectives=["accuracy"], configuration_space={"t": [0]})
            def probe(question: str) -> str:
                return "a"

            outcome[label] = "accepted"
        except Exception as exc:
            outcome[label] = type(exc).__name__
    emit(outcome)
    """
    outcome = _run_driver(tmp_path, "", body)
    assert "accepted" not in outcome.values(), (
        "EvaluationOptions now accepts a BaseEvaluator: revisit the Tier 5 "
        f"'not wireable' note in traigent-eval-build/SKILL.md. outcome={outcome}"
    )
