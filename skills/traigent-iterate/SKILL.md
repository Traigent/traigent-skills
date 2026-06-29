---
name: traigent-iterate
description: "Decide what to do after a Traigent optimization run. Use when results are flat, noisy, negative, budget-bound, or tied with baseline; when users ask what next after a run, which knob mattered, expand or narrow the space, use weak examples, inspect example-side evidence, compare runs, or choose the next iteration hypothesis."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.2.3"
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

For a cloud/portal run, the fastest way to get the evidence is the terminal-first decision
brief in `traigent-analyze-results` (the `traigent-analytics` MCP `analytics_get_run_decision_brief`
tool). Read the brief first and base the next iteration on its real fields:

- `confidence` - keep low/medium confidence visible; do not upgrade it based on intuition.
- `evidence[].summary` - use these summaries to identify whether the issue is flat scores,
  noisy examples, high cost, thin samples, a dominated winner, or a narrow knob.
- `recommended_action.kind` - use the backend's action as the starting point, then use the
  symptom rows below to turn it into one concrete next hypothesis.

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

<!-- PROTECTED -->
Use example-side evidence when the aggregate score hides where the candidate wins or fails. `ExampleInsightsClient` requires a Traigent account/backend and returns scoring metadata only: example ids, sample counts, algorithm version, and scored flags. It does not expose proprietary difficulty, informativeness, ambiguity, or latent feature-vector values. The ranked and flagged "examples to review" surface (`analytics_get_example_insights` / `GET /runs/{run_id}/example-insights`) is likewise non-signal: it ranks by review urgency and provides enum flags and a suggested action — never raw scores or hidden feature values.
<!-- /PROTECTED -->

> **Deprecated:** `traigent.analytics` is deprecated since SDK 0.9.0. Use the `traigent-analytics` plugin: `pip install traigent-analytics` and import from `traigent_analytics` instead.

```python
from traigent_analytics import ExampleInsightsClient  # canonical (traigent-analytics plugin)
# from traigent.analytics import ExampleInsightsClient  # deprecated shim — still works

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

When aggregate scores hide where the candidate wins or fails, pull the ranked "examples to review" rows: use the `analytics_get_example_insights` MCP tool or `client.get_example_insights(run_id)` from the analytics client. Work through rows in `review_priority` order (critical first) and use each row's `suspicious_flags` and `recommended_action` to choose the next iteration — these are coarse enum signals, not hidden numeric scores. See `traigent-curate-dataset` for the flag-to-action guide.

Backend-only report surfaces, each requiring a Traigent account/backend:

- `GET /api/v1/experiment-runs/runs/{run_id}/report-payload`: winner, trade-off, and stability insights.
- `/api/v1/optimization-comparisons`: cross-run comparison across candidate runs.
- Example-scoring compute, scores, and dataset-quality endpoints: scoring status and scoring metadata.
- `GET /api/v1/analytics/runs/{run_id}/example-insights`: ranked and flagged examples to review (IP-safe: review_priority, suspicious_flags, recommended_action).

## Next-Step Decision Table

| Symptom | Likely read | Ranked next action |
|---|---|---|
| Flat scores everywhere | Evaluation dataset is too easy, objective is saturated, or the space lacks meaningful variation | Synthesize harder examples with `traigent-curate-dataset`; add discriminating cases; then re-run a small grid |
| High variance across repetitions | Evaluator or model behavior is noisy | Raise repetitions, use statistical aggregation, and audit the evaluator with `traigent-evaluator-audit`. A server-side ACET `audit_evaluator` action (computed from the run's tensor) is coming as a next-step option — prefer it when available. |
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

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

- Always be concise.
- Match terminology to expertise. For `se`: plain engineering words; define each Traigent or
  statistics term once in plain language (no Bayesian / variance-decomposition / Pareto jargon
  unless asked). For `ds`: compact optimization and statistical terms are fine.
- Presenting options: show at most 3, mark exactly one **Recommended**, and give one short
  persona-appropriate trade-off per option.
- Autonomy. For `delegate` or `execute`: pick the recommended reversible action and proceed, asking
  only at hard gates. For `guided`: offer options with a recommendation at the key decisions. For
  `inspect` or `explore`: give brief rationale or evidence before asking, and ask before branch
  choices.
- Hard gates — always confirm regardless of persona: paid or provider model calls, sending data or
  private content off the machine, destructive edits, decisions the Traigent service is meant to
  return, and any missing fact the step truly requires.
- Always end by recommending the next Traigent skill or action to take.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
