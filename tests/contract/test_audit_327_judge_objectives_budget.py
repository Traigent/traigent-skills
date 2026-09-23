"""Issue #327: judge templates must minimize judge_cost and cap judge spend per run.

A plain ``objectives=[..., "judge_cost"]`` list defaults the unrecognized name to
``maximize``, so the optimizer rewarded judge spend. The old "guardrail" compared
one per-example constant with the cap and never stopped a judge call. The judge
and hybrid templates are executed here offline (agent and judge replies come from
litellm's own ``mock_response``) and must: orient ``judge_cost`` as minimize with
no unrecognized-objective warning, make at most floor(cap / price) judge calls
across the whole run, and still fail parse failures closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .test_audit_326_comparator_case import _python_block, _run_driver

TEMPLATES = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-eval-build"
    / "references"
    / "evaluator-templates.md"
)
JUDGE_MARKER = "def llm_judge_evaluator"
HYBRID_MARKER = "def hybrid_evaluator"

ORIENTATION_BODY = """
import warnings
write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
write_rows("extraction.jsonl", [{"input": {"text": "t"}, "output": {"label": "a"}}])
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    ns = load_block(sys.argv[1])
fn = ns.get("answer") or ns.get("extract")
emit({
    "orientation": {o.name: o.orientation for o in fn.objective_schema.objectives},
    "unrecognized": [str(w.message) for w in caught if "not a recognized metric name" in str(w.message)],
})
"""


def test_judge_template_minimizes_judge_cost(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path, _python_block(TEMPLATES, JUDGE_MARKER), ORIENTATION_BODY
    )
    assert result["orientation"] == {"quality": "maximize", "judge_cost": "minimize"}
    assert result["unrecognized"] == [], result


def test_hybrid_template_minimizes_judge_cost(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path, _python_block(TEMPLATES, HYBRID_MARKER), ORIENTATION_BODY
    )
    assert result["orientation"] == {
        "valid_json": "maximize",
        "quality": "maximize",
        "judge_cost": "minimize",
    }
    assert result["unrecognized"] == [], result


@pytest.mark.parametrize("marker", [JUDGE_MARKER, HYBRID_MARKER])
def test_spend_limits_are_not_tuned_variables(marker: str) -> None:
    block = _python_block(TEMPLATES, marker)
    assert "max_judge_calls" not in block
    assert "max_judge_cost_usd" not in block


def test_judge_budget_caps_calls_across_the_whole_run(tmp_path: Path) -> None:
    """$0.01 cap at $0.002 per call: 5 of the 8 attempted judge calls (4 rows x 2 trials)."""
    body = """
    judge_calls = []
    def reply(model, messages):
        if model == ns["JUDGE_MODEL"]:
            judge_calls.append(1)
            return '{"score": 1.0, "reason": "ok"}'
        return "Paris"
    install_replies(reply)
    write_rows("qa.jsonl", [{"input": {"question": f"Q{i}?"}, "output": "Paris"} for i in range(4)])
    ns = load_block(sys.argv[1])
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=0.01, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
    result = ns["answer"].optimize_sync(algorithm="grid", max_trials=2)
    emit({"judge_calls": len(judge_calls), "spent": ns["JUDGE_BUDGET"].spent,
          "quality": [t.metrics.get("quality") for t in result.trials]})
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, JUDGE_MARKER), body)
    assert result["judge_calls"] == 5, result
    assert abs(result["spent"] - 0.01) < 1e-9, result


def test_judge_budget_refusals_and_parse_failures_fail_closed(tmp_path: Path) -> None:
    body = """
    from types import SimpleNamespace
    install_replies(lambda model, messages: "Paris")
    write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "Paris"}])
    ns = load_block(sys.argv[1])
    example = SimpleNamespace(input_data={"question": "q"}, expected_output="Paris", metadata={"id": "row-1"})
    agent = lambda question: "Paris"
    install_replies(lambda model, messages: "not json at all")
    parse_fail = ns["llm_judge_evaluator"](agent, {}, example)
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=0.0, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
    refused = ns["llm_judge_evaluator"](agent, {}, example)
    emit({
        "parse_fail": [parse_fail.success, parse_fail.metrics["quality"], parse_fail.error_message],
        "refused": [refused.success, refused.metrics["quality"], refused.error_message],
    })
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, JUDGE_MARKER), body)
    assert result["parse_fail"] == [False, 0.0, "judge_parse_failure"], result
    assert result["refused"] == [False, 0.0, "judge_budget_exhausted"], result


def test_hybrid_judge_budget_caps_calls_across_the_whole_run(tmp_path: Path) -> None:
    """Same cap for the gate-then-judge template: 5 of 8 judge calls at $0.01 / $0.002."""
    body = """
    judge_calls = []
    def reply(model, messages):
        if model == ns["JUDGE_MODEL"]:
            judge_calls.append(1)
            return '{"score": 1.0, "reason": "ok"}'
        return '{"label": "billing"}'
    install_replies(reply)
    write_rows("extraction.jsonl", [{"input": {"text": f"Invoice {i}"}, "output": {"label": "billing"}} for i in range(4)])
    ns = load_block(sys.argv[1])
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=0.01, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
    result = ns["extract"].optimize_sync(algorithm="grid", max_trials=2)
    emit({"judge_calls": len(judge_calls), "spent": ns["JUDGE_BUDGET"].spent})
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, HYBRID_MARKER), body)
    assert result["judge_calls"] == 5, result
    assert abs(result["spent"] - 0.01) < 1e-9, result


def test_hybrid_refusals_and_parse_failures_fail_closed(tmp_path: Path) -> None:
    body = """
    from types import SimpleNamespace
    install_replies(lambda model, messages: "not json at all")
    write_rows("extraction.jsonl", [{"input": {"text": "t"}, "output": {"label": "a"}}])
    ns = load_block(sys.argv[1])
    example = SimpleNamespace(input_data={"text": "t"}, expected_output={"label": "a"}, metadata={"id": "row-1"})
    agent = lambda text: '{"label": "a"}'
    parse_fail = ns["hybrid_evaluator"](agent, {}, example)
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=0.0, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
    refused = ns["hybrid_evaluator"](agent, {}, example)
    emit({
        "parse_fail": [parse_fail.success, parse_fail.metrics["quality"], parse_fail.error_message],
        "refused": [refused.success, refused.metrics["quality"], refused.error_message,
                    refused.metadata.get("judge_called")],
    })
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, HYBRID_MARKER), body)
    assert result["parse_fail"] == [False, 0.0, "judge_parse_failure"], result
    assert result["refused"] == [False, 0.0, "judge_budget_exhausted", False], result
