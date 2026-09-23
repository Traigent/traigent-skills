"""Issue #328: the statistical template must pin its repetition count.

With ``eval_reps`` in ``configuration_space`` the optimizer compared trials
measured with different instruments (agreement is biased upward at small n), and
``accuracy`` was a majority vote, which overstates what one production call does.
The template is executed offline with a fixed reply cycle (3 of 5 samples
correct per row): every trial must make the same number of agent calls per row,
and ``accuracy`` must be the per-sample rate (0.6), not the majority vote (1.0).
"""

from __future__ import annotations

from pathlib import Path

from .test_audit_326_comparator_case import _python_block, _run_driver

TEMPLATES = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-eval-build"
    / "references"
    / "evaluator-templates.md"
)
MARKER = "def statistical_agreement_evaluator"
ROWS = 4


def test_repetition_count_is_not_a_tuned_variable() -> None:
    block = _python_block(TEMPLATES, MARKER)
    assert '"eval_reps"' not in block


def test_every_trial_uses_the_same_reps_and_per_sample_accuracy(
    tmp_path: Path,
) -> None:
    body = f"""
    import collections
    import traigent
    cycle = ["Paris", "paris", " PARIS ", "Lyon", "Nice"]
    position = [0]
    def reply(model, messages):
        value = cycle[position[0] % len(cycle)]
        position[0] += 1
        return value
    install_replies(reply)
    write_rows("qa.jsonl", [{{"input": {{"question": f"Q{{i}}?"}}, "output": "paris"}} for i in range({ROWS})])
    ns = load_block(sys.argv[1])
    calls_per_config = collections.Counter()
    real_prompt_model = ns["prompt_model"]
    def counting_prompt_model(prompt, **kwargs):
        calls_per_config[json.dumps(dict(traigent.get_config()), sort_keys=True)] += 1
        return real_prompt_model(prompt, **kwargs)
    ns["prompt_model"] = counting_prompt_model
    result = ns["answer"].optimize_sync(algorithm="grid", max_trials=4)
    emit({{
        "calls_per_row": sorted({{count / {ROWS} for count in calls_per_config.values()}}),
        "configs": len(calls_per_config),
        "metrics": [t.metrics for t in result.trials],
        "example_diagnostics": [
            {{k: row["metrics"].get(k) for k in ("agreement", "majority_accuracy")}}
            for t in result.trials for row in (t.metadata or {{}}).get("example_results") or []
        ],
    }})
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, MARKER), body)
    assert result["configs"] >= 2, result
    assert len(result["calls_per_row"]) == 1, (
        f"trials used different repetition counts: {result}"
    )
    for metrics in result["metrics"]:
        assert abs(metrics["accuracy"] - 0.6) < 1e-9, result
    # The diagnostics are documented as readable per row from the trial metadata.
    diagnostics = result["example_diagnostics"]
    assert diagnostics and all(
        row == {"agreement": 0.6, "majority_accuracy": 1.0} for row in diagnostics
    ), result
