"""Issue #330: a Tier 4 custom evaluator must emit ``latency`` itself, in milliseconds.

The SDK's custom-evaluator wrapper records ``execution_time_ms`` but never the
bare ``latency`` key the objective binds to, and a missing objective key averages
in as 0.0. The Tier 4 example of ``traigent-eval-build/SKILL.md`` is executed
offline with ``objectives=["accuracy", "latency"]`` and a ~50 ms agent: latency
must be non-zero milliseconds. Tier 2 (built-in latency) is the unchanged control.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest
from packaging.version import Version

from .test_audit_326_comparator_case import _python_block, _run_driver

SKILLS = Path(__file__).resolve().parents[2] / "skills"
EVAL_BUILD = SKILLS / "traigent-eval-build" / "SKILL.md"

BODY = """
import time
def slow_reply(model, messages):
    time.sleep(0.05)
    return "paris"
install_replies(slow_reply)
write_rows("qa.jsonl", [{"input": {"question": f"Q{i}?"}, "output": "paris"} for i in range(3)])
ns = load_block(sys.argv[1])
result = ns["answer"].optimize_sync(algorithm="grid", max_trials=2)
emit([t.metrics.get("latency") for t in result.trials])
"""


def _with_latency_objective(block: str) -> str:
    assert block.count('objectives=["accuracy"]') == 1
    return block.replace(
        'objectives=["accuracy"]', 'objectives=["accuracy", "latency"]'
    )


def test_tier4_custom_evaluator_reports_latency_in_ms(tmp_path: Path) -> None:
    block = _with_latency_objective(_python_block(EVAL_BUILD, "def evaluate_answer"))
    latencies = _run_driver(tmp_path, block, BODY)
    assert len(latencies) == 2, latencies
    # 50 ms per call: milliseconds, not 0.0 and not seconds (~0.05).
    assert all(value is not None and 40.0 <= value < 5000.0 for value in latencies), (
        latencies
    )


@pytest.mark.skipif(
    Version(importlib.metadata.version("traigent")) < Version("0.23.0"),
    reason="built-in latency is seconds before 0.23.0 (version-matrix: latency-unit)",
)
def test_tier2_builtin_latency_is_unchanged(tmp_path: Path) -> None:
    block = _with_latency_objective(_python_block(EVAL_BUILD, "def exact_match_score"))
    latencies = _run_driver(tmp_path, block, BODY)
    assert all(value is not None and value >= 40.0 for value in latencies), latencies


def test_ladder_and_choose_metric_state_the_rule() -> None:
    build = EVAL_BUILD.read_text(encoding="utf-8")
    assert "A `custom_evaluator` does not produce `latency`." in build
    choose = (SKILLS / "traigent-eval-choose-metric" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    row = next(
        line
        for line in choose.splitlines()
        if line.startswith('| `["accuracy", "latency"]`')
    )
    assert 'metrics["latency"]' in row
