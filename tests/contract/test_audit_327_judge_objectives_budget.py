"""Issue #327: judge templates must minimize judge_cost and cap judge spend per run.

A plain ``objectives=[..., "judge_cost"]`` list defaults the unrecognized name to
``maximize``, so the optimizer rewarded judge spend. The old "guardrail" compared
one per-example constant with the cap and never stopped a judge call. The judge
and hybrid templates are executed here offline (agent and judge replies come from
litellm's own ``mock_response``) and must: orient ``judge_cost`` as minimize with
no unrecognized-objective warning, make at most floor(cap / price) judge calls
per run, and still fail parse failures closed.

Review round 2: a refused row scores 0.0 and is averaged into its trial, so
budget exhaustion silently biased the ranking, and the budget was process-global.
The budget is now built fresh per run by ``run_with_judge_budget``, which refuses
to start when the cap cannot cover rows x trials and raises when any call was
refused; an unset budget raises instead of scoring 0.0.
"""

from __future__ import annotations

import re
import textwrap
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


# Each template: (marker, decorated function, dataset file, row input, agent reply).
TEMPLATE_CASES = {
    "judge": (JUDGE_MARKER, "answer", "qa.jsonl", {"question": "Q{i}?"}, "Paris"),
    "hybrid": (
        HYBRID_MARKER,
        "extract",
        "extraction.jsonl",
        {"text": "Invoice {i}"},
        '{"label": "billing"}',
    ),
}

RUN_PRELUDE = """
judge_calls = []
def reply(model, messages):
    if model == ns["JUDGE_MODEL"]:
        judge_calls.append(1)
        return '{{"score": 1.0, "reason": "ok"}}'
    return {agent_reply!r}
install_replies(reply)
write_rows({dataset!r}, [{{"input": {{k: v.format(i=i) for k, v in {row_input!r}.items()}}, "output": "Paris"}} for i in range(4)])
ns = load_block(sys.argv[1])
fn = ns[{fn_name!r}]
price = ns["JUDGE_COST_PER_CALL_USD"]
def run(**kwargs):
    before = len(judge_calls)
    try:
        result = ns["run_with_judge_budget"](fn, algorithm="grid", **kwargs)
        return {{"raised": None, "judge_calls": len(judge_calls) - before,
                "quality": [t.metrics.get("quality") for t in result.trials]}}
    except Exception as exc:
        return {{"raised": f"{{type(exc).__name__}}: {{exc}}", "judge_calls": len(judge_calls) - before}}
"""


def _run_template(tmp_path: Path, case: str, body: str) -> dict:
    marker, fn_name, dataset, row_input, agent_reply = TEMPLATE_CASES[case]
    prelude = RUN_PRELUDE.format(
        agent_reply=agent_reply, dataset=dataset, row_input=row_input, fn_name=fn_name
    )
    return _run_driver(
        tmp_path, _python_block(TEMPLATES, marker), prelude + textwrap.dedent(body)
    )


@pytest.mark.parametrize("case", sorted(TEMPLATE_CASES))
def test_budget_too_small_for_the_run_is_refused_before_spending(
    case: str, tmp_path: Path
) -> None:
    """$0.01 cannot cover 4 rows x 2 trials at $0.002: refuse up front, no judge call."""
    result = _run_template(
        tmp_path, case, "emit(run(rows=4, max_trials=2, cap_usd=0.01))\n"
    )
    assert result["raised"] and result["raised"].startswith("ValueError"), result
    assert result["judge_calls"] == 0, result


@pytest.mark.parametrize("case", sorted(TEMPLATE_CASES))
def test_exhaustion_mid_run_raises_instead_of_ranking(
    case: str, tmp_path: Path
) -> None:
    """Row count under-declared (2 instead of 4): the cap binds mid-run and the run raises."""
    result = _run_template(
        tmp_path, case, "emit(run(rows=2, max_trials=2, cap_usd=2 * 2 * price))\n"
    )
    assert result["judge_calls"] == 4, result  # the cap still holds: 4 of 8 calls
    assert result["raised"] and result["raised"].startswith("RuntimeError"), result
    assert "4 judge call(s) refused" in result["raised"], result


@pytest.mark.parametrize("case", sorted(TEMPLATE_CASES))
def test_budget_is_fresh_for_every_run(case: str, tmp_path: Path) -> None:
    """A second run in the same process starts with a full budget, and identical trials tie."""
    body = """
    first = run(rows=4, max_trials=2, cap_usd=4 * 2 * price)
    second = run(rows=4, max_trials=2, cap_usd=4 * 2 * price)
    emit({"first": first, "second": second})
    """
    result = _run_template(tmp_path, case, body)
    for key in ("first", "second"):
        run_result = result[key]
        assert run_result["raised"] is None, result
        assert run_result["judge_calls"] == 8, result
        assert run_result["quality"] == [1.0, 1.0], result


@pytest.mark.parametrize("case", sorted(TEMPLATE_CASES))
def test_unset_budget_raises_instead_of_scoring_zero(case: str, tmp_path: Path) -> None:
    marker, *_ = TEMPLATE_CASES[case]
    evaluator = marker.removeprefix("def ")
    body = f"""
    from types import SimpleNamespace
    example = SimpleNamespace(input_data={{"question": "q", "text": "t"}}, expected_output="Paris", metadata={{}})
    agent = lambda **kwargs: {TEMPLATE_CASES[case][4]!r}
    try:
        outcome = ns[{evaluator!r}](agent, {{}}, example)
        emit({{"raised": None, "success": outcome.success, "quality": outcome.metrics.get("quality")}})
    except RuntimeError as exc:
        emit({{"raised": str(exc)}})
    """
    result = _run_template(tmp_path, case, body)
    assert result["raised"] and "run_with_judge_budget" in result["raised"], result


def test_judge_refusals_and_parse_failures_fail_closed(tmp_path: Path) -> None:
    body = """
    from types import SimpleNamespace
    install_replies(lambda model, messages: "Paris")
    write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "Paris"}])
    ns = load_block(sys.argv[1])
    example = SimpleNamespace(input_data={"question": "q"}, expected_output="Paris", metadata={"id": "row-1"})
    agent = lambda question: "Paris"
    install_replies(lambda model, messages: "not json at all")
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=1.0, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
    parse_fail = ns["llm_judge_evaluator"](agent, {}, example)
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=0.0, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
    refused = ns["llm_judge_evaluator"](agent, {}, example)
    emit({
        "parse_fail": [parse_fail.success, parse_fail.metrics["quality"], parse_fail.error_message],
        "refused": [refused.success, refused.metrics["quality"], refused.error_message],
        "refused_count": ns["JUDGE_BUDGET"].refused,
    })
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, JUDGE_MARKER), body)
    assert result["parse_fail"] == [False, 0.0, "judge_parse_failure"], result
    assert result["refused"] == [False, 0.0, "judge_budget_exhausted"], result
    assert result["refused_count"] == 1, result


def test_hybrid_refusals_and_parse_failures_fail_closed(tmp_path: Path) -> None:
    body = """
    from types import SimpleNamespace
    install_replies(lambda model, messages: "not json at all")
    write_rows("extraction.jsonl", [{"input": {"text": "t"}, "output": {"label": "a"}}])
    ns = load_block(sys.argv[1])
    example = SimpleNamespace(input_data={"text": "t"}, expected_output={"label": "a"}, metadata={"id": "row-1"})
    agent = lambda text: '{"label": "a"}'
    ns["JUDGE_BUDGET"] = ns["JudgeBudget"](cap_usd=1.0, per_call_usd=ns["JUDGE_COST_PER_CALL_USD"])
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


THREAD_SAFETY_BODY = """
import threading
# load_block runs the template's @traigent.optimize, which validates its dataset path.
write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
write_rows("extraction.jsonl", [{"input": {"text": "t"}, "output": {"label": "a"}}])
ns = load_block(sys.argv[1])
Budget = ns["JudgeBudget"]

class HeldLock:
    # Wraps the real lock and records whether it is held, so writes can be checked.
    def __init__(self):
        self.inner, self.held, self.entries = threading.Lock(), False, 0
    def __enter__(self):
        self.inner.acquire()
        self.held, self.entries = True, self.entries + 1
    def __exit__(self, *exc):
        self.held = False
        self.inner.release()

unlocked_writes = []
class CheckedBudget(Budget):
    def __setattr__(self, name, value):
        lock = self.__dict__.get("_lock")
        if name in ("spent", "refused") and isinstance(lock, HeldLock) and not lock.held:
            unlocked_writes.append(name)
        super().__setattr__(name, value)

# Deterministic: every read-modify-write of the counters happens under the lock.
budget = CheckedBudget(cap_usd=0.01, per_call_usd=0.002)
budget._lock = HeldLock()
granted = [budget.try_spend() for _ in range(8)]

# Stress: 64 threads released together still get exactly floor(cap / price) calls.
stress = []
for _ in range(10):
    shared = Budget(cap_usd=0.01, per_call_usd=0.002)
    barrier = threading.Barrier(64)
    results = []
    def worker():
        barrier.wait()
        results.append(shared.try_spend())
    threads = [threading.Thread(target=worker) for _ in range(64)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stress.append([sum(results), shared.refused])
emit({"granted": sum(granted), "refused": budget.refused, "lock_entries": budget._lock.entries,
      "unlocked_writes": unlocked_writes, "stress": stress})
"""


@pytest.mark.parametrize("marker", [JUDGE_MARKER, HYBRID_MARKER])
def test_judge_budget_updates_counters_under_its_lock(
    marker: str, tmp_path: Path
) -> None:
    result = _run_driver(tmp_path, _python_block(TEMPLATES, marker), THREAD_SAFETY_BODY)
    assert result["unlocked_writes"] == [], result
    assert result["lock_entries"] == 8, result  # every try_spend call takes the lock
    assert (result["granted"], result["refused"]) == (5, 3), result
    assert result["stress"] == [[5, 59]] * 10, result


def test_judge_prose_bullet_count_matches_its_lead_in() -> None:
    text = TEMPLATES.read_text(encoding="utf-8")
    section = text.split("## LLM judge with rubric", 1)[1].split("```python", 1)[0]
    lead = re.search(r"^(\w+) things the template does on purpose:$", section, re.M)
    assert lead, "missing lead-in sentence"
    bullets = re.findall(r"^- \*\*", section, re.M)
    words = {"two": 2, "three": 3, "four": 4, "five": 5}
    assert words[lead.group(1).lower()] == len(bullets), (lead.group(0), len(bullets))
