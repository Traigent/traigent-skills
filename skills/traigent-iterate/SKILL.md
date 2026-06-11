---
name: traigent-iterate
description: "Decide what to do after a Traigent optimization run. Use when results are flat, noisy, negative, budget-bound, or tied with baseline; when users ask what next after a run, which knob mattered, expand or narrow the space, use weak examples, inspect example-side evidence, compare runs, or choose the next iteration hypothesis."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0"
---

# Iterate After a Run

## When to Use

Use this skill after a Traigent optimization run when the user asks:

- "results are flat/noisy/negative"
- "what next after a run?"
- "which knob mattered?"
- "should I expand or narrow the space?"
- "what do I do with weak examples?"

The goal is to choose the next single hypothesis, not to change every part of the system at once.

## Read the Evidence First

Start with the run object and existing analysis skills. `traigent-analyze-results` covers result fields in depth, and `show-significant-tuned-variables` covers richer importance reporting. Use this skill to decide the next action after those facts are known.

```python
from traigent.utils.insights import get_optimization_insights
from traigent.utils.importance import ParameterImportanceAnalyzer

print(f"stop_reason={results.stop_reason}")
print(f"best_config={results.best_config}")
print(f"trial_count={len(results.trials)}")
print(f"total_cost={results.total_cost}")

insights = get_optimization_insights(results)
print(insights.get("performance_summary", {}))
print(insights.get("parameter_insights", {}))

analyzer = ParameterImportanceAnalyzer(objective="accuracy")
importance = analyzer.analyze_variance_based(results.trials)
print(analyzer.get_top_parameters(importance, top_k=5))
```

If importance is empty, do not infer that no knob matters. Common reasons are too few successful trials, flat objective variance, missing objective metrics, or a configuration space that did not vary enough.

## Example-Side Evidence

Use example-side evidence when the aggregate score hides where the candidate wins or fails. `ExampleInsightsClient` requires a Traigent account/backend and returns non-signal scoring metadata only: example ids, sample counts, algorithm version, and scored flags. It does not expose proprietary difficulty, informativeness, ambiguity, or signal-vector values.

```python
from traigent.analytics import ExampleInsightsClient

async def fetch_example_metadata(run_id: str):
    async with ExampleInsightsClient(
        backend_url="https://portal.traigent.ai",
        timeout=60.0,
    ) as client:
        job = await client.compute_scores(experiment_run_id=run_id)
        status = await client.get_job_status(job_id=job["job_id"])
        scores = await client.get_example_scores(experiment_run_id=run_id)
        quality = await client.get_dataset_quality(experiment_run_id=run_id)
        return {"status": status, "scores": scores, "quality": quality}
```

Backend-only report surfaces, each requiring a Traigent account/backend:

- `GET /api/v1/experiment-runs/runs/{run_id}/report-payload`: winner, trade-off, and stability insights.
- `/api/v1/optimization-comparisons`: cross-run comparison across candidate runs.
- Example-scoring compute, scores, and dataset-quality endpoints: scoring status and non-signal metadata.

Planned: future curation-advice endpoints may package weak-example recommendations; until then, use the manual evidence loop below.

## Next-Step Decision Table

| Symptom | Likely read | Ranked next action |
|---|---|---|
| Flat scores everywhere | Evaluation dataset is too easy, objective is saturated, or the space lacks meaningful variation | Synthesize harder examples with `traigent-curate-dataset`; add discriminating cases; then re-run a small grid |
| High variance across repetitions | Evaluator or model behavior is noisy | Raise repetitions, use statistical aggregation, and audit the evaluator with `traigent-evaluator-audit` |
| One knob dominates | The useful region is narrower than the current space | Narrow that knob's range; add structural knobs with `traigent-configuration-space` or `traigent-composite-knobs` |
| Winner ties baseline | Objective weights or threshold may not reflect the product decision | Revisit objective weights with `traigent-choose-metric`; inspect holdout slices before changing the space |
| `stop_reason` is budget-bound | Search stopped before enough evidence accumulated | Adjust budget, cheaper models, max trials, or algorithm with `traigent-run-optimization` |
| Weak examples identified | The same examples fail across good configs | Feed those examples into guided optimization and add a heldout check |

Use weak examples as evidence, not as a replacement for a holdout.

```python
weak_examples = [
    ("question text", "expected answer", "candidate answer"),
]

results = await answer.optimize_with_guidance(
    provider=provider,
    weak_examples=weak_examples,
    max_trials=8,
)
```

`optimize_with_guidance` is a method on the decorated optimized function. Keep the provider and rewrite settings project-specific, and confirm the new candidate still improves on a heldout slice.

## One Iteration = One Hypothesis

Change one thing per round. Good iteration statements look like:

- "Scores are flat because the evaluation dataset lacks hard negatives; add 30 hard negatives."
- "Variance is high because the LLM judge flips on borderline cases; raise repetitions and demote to statistical aggregation."
- "Temperature dominates; narrow temperature and add a retrieval-depth structural knob."

For each round:

1. Write the hypothesis.
2. Make one change.
3. Re-run on the same holdout.
4. Compare to the pinned baseline and previous candidate.
5. Keep a tiny iteration log.

Use `references/iteration-log-template.md` as the 10-line per-iteration log.

## Claim Scope

Iteration decisions are local to the current evaluation dataset, holdout, objective, evaluator, configuration space, and budget. A better next action on one slice does not imply the same action is best after the dataset, evaluator, model provider, or objective weights change.

## See Also

- `traigent-analyze-results` - field-level result reading and stop-reason interpretation.
- `show-significant-tuned-variables` - deeper tuned-variable importance and video-card output.
- `traigent-curate-dataset` - build harder or better-targeted evaluation data.
- `traigent-evaluator-audit` - diagnose noisy or biased judge metrics.
- `traigent-configuration-space` - narrow or expand tuned variables.
- `traigent-composite-knobs` - add structural knobs when scalar knobs are not enough.
- `traigent-run-optimization` - adjust algorithms, trial budgets, and cost controls.
