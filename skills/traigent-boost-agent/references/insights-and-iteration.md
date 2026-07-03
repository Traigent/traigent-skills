# Insights and Iteration

Use this reference for step 10 of `traigent-boost-agent`: read configuration-side results, inspect example-side metadata, then choose one next hypothesis.

## Configuration-Side Insight

Start with the SDK insight helper, then add an importance pass before saying which tuned variables mattered.

```python
from traigent.utils.insights import get_optimization_insights
from traigent.utils.importance import ParameterImportanceAnalyzer

insights = get_optimization_insights(results)
print(insights.get("performance_summary", {}))
print(insights.get("parameter_insights", {}))
print(insights.get("recommendations", []))

analyzer = ParameterImportanceAnalyzer(objective="accuracy")
importance = analyzer.analyze_variance_based(results.trials)

for item in analyzer.get_top_parameters(importance, top_k=5):
    print(
        f"{item.parameter_name}: "
        f"importance={item.importance_score:.3f}, "
        f"ci={item.confidence_interval}, "
        f"n={item.sample_size}"
    )
```

If the importance result is empty, report that as insufficient evidence. Do not infer that no variable matters unless the run had enough successful, varied trials and enough objective variance to support that read.

For richer export artifacts and honest `directional` vs `significant` labels, delegate to `show-significant-tuned-variables`.

## Example-Side Insight

Use example-side evidence when aggregate scores hide where the candidate wins or fails. `ExampleInsightsClient` requires a Traigent backend/account. The honest reportable scope is non-signal metadata such as job status, example ids, sample counts, algorithm version, and scored flags. It does not expose proprietary difficulty, informativeness, ambiguity, or signal-vector values.

> **Import note (verified against SDK 0.18.x):** `ExampleInsightsClient` ships in the core SDK at `traigent.analytics` — no separate install required. The module's own `DeprecationWarning` points at the separate `traigent-analytics` plugin, but that plugin does not export `ExampleInsightsClient` (`from traigent_analytics import ExampleInsightsClient` raises `ImportError`); use the core import below and ignore the warning for this class. **Caveat if you HAVE installed the plugin:** the core shim then defers to the plugin and stops exposing this class, so the import below itself raises `ImportError` — uninstall the plugin or use the deep import `from traigent.analytics.example_insights import ExampleInsightsClient` (works with or without the plugin, verified).

```python
from traigent.analytics import ExampleInsightsClient


async def fetch_example_insights(
    run_id: str,
    backend_url: str,
    api_key: str | None = None,
) -> dict:
    async with ExampleInsightsClient(
        backend_url=backend_url,
        api_key=api_key,
        timeout=60.0,
    ) as client:
        job = await client.compute_scores(experiment_run_id=run_id)
        status = await client.get_job_status(job_id=job["job_id"])
        scores = await client.get_example_scores(experiment_run_id=run_id)
        quality = await client.get_dataset_quality(experiment_run_id=run_id)
        return {
            "job": job,
            "status": status,
            "scores": scores,
            "quality": quality,
        }
```

Use these outputs to target curation or audit work, not to claim hidden causal explanations.

The `analytics_get_example_insights` MCP tool (or `GET /api/v1/analytics/runs/{run_id}/example-insights`) provides a ranked and flagged complement: up to 100 rows ordered by `review_priority` (critical | high | medium | low), each with `suspicious_flags` and a `recommended_action`. This surface is non-signal — it ranks by review urgency and provides enum flags, not raw scores or formulas. Use the flag-to-action guide below when acting on these rows.

## Symptom-to-Next-Step Table

| Symptom | Next action | Owning skill |
|---|---|---|
| Scores are flat everywhere | Add harder or more discriminating examples, then rerun a small controlled search | `traigent-curate-dataset` |
| Winner ties baseline but product tradeoff still feels wrong | Revisit the objective, weights, or decision threshold before changing code | `traigent-choose-metric` |
| Evaluator flips on repetitions or judge output is noisy | Audit agreement, repetition stability, bias, parse failures, and calibration | `traigent-evaluator-audit` |
| Evaluator cannot express the chosen metric | Wire a stronger deterministic, statistical, hybrid, or `BaseEvaluator` path | `traigent-build-evaluator` |
| One tuned variable dominates the run | Narrow that variable's range and rerun with a focused hypothesis | `traigent-configuration-space` |
| Scalar knobs are not enough for the agent shape | Add a composite pattern that matches the codebase shape | `traigent-composite-knobs` |
| Search stopped because of budget or trials | Adjust algorithm, `max_trials`, parallelism, model mix, or cost limit after approval | `traigent-run-optimization` |
| Weak examples recur across good configs | Feed weak examples into the curation loop and preserve a heldout check | `traigent-curate-dataset` |
| Candidate looks promotable | Compare candidate vs incumbent on the same holdout and add CI checks | `traigent-ci-safety-gate` |
| `analytics_get_example_insights` returns critical or high rows | Work in `review_priority` order; apply the flag-to-action guide below | `traigent-curate-dataset` |

Use `traigent-iterate` to choose the next single hypothesis after these facts are known.

### Suspicious Flag → Next Action

When the example-insights surface flags rows, map each `suspicious_flag` to a curation action:

| suspicious_flag | Next action |
|---|---|
| `possible_mislabel` | Re-check the expected answer / rubric before any dataset change |
| `redundant_pattern` | Remove or dedupe; broaden coverage elsewhere in the dataset |
| `anomalous_low_success` | Clarify the expected output, or mark as a deliberate hard case |
| `high_response_variance` | Clarify acceptable answers or increase repetitions |
| `low_agent_strength_correlation` | Review the example label or the evaluator for this example |
| `low_sample_support` | Rerun for more evidence before making a permanent dataset change |
