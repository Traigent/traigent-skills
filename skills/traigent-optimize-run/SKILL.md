---
name: traigent-optimize-run
description: "Run Traigent optimization: async/sync execution, algorithm selection, cost limits, stop conditions, and parallel trials. Use when calling func.optimize() or optimize_sync(), choosing algorithms (auto/grid/random anywhere; named smart selectors like bayesian/optuna on authenticated connected runs, SDK 0.20.1+), setting max_trials or cost_limit, configuring parallel execution, or handling CostLimitExceeded."
license: Apache-2.0
metadata:
  traigent-audience: sdk-user
  traigent-topic: agent-optimization
  traigent-stage: optimize
  traigent-maturity: stable
  author: Nimrod
  version: "1.0.13"
---

# Running Traigent Optimization

## When to Use

Use this skill after you have decorated a function with `@traigent.optimize()` and need to:

- Run optimization (async or sync)
- Choose an algorithm (`auto` for connected real runs; `grid`/`random` for explicit local/offline search; named smart selectors like `bayesian`/`tpe`/`optuna` on authenticated connected runs, SDK 0.20.1+)
- Set trial limits, timeouts, or cost budgets
- Configure parallel trial execution
- Handle cost limit exceptions
- Interpret stop reasons and results

## Objective Naming Rule

Default: at least one objective labeled `accuracy` (built-in objective or your `metric_functions` key). If accuracy doesn't apply to this problem, name the primary quality KPI after the product concept, for example `valid_schema`, and note why accuracy was skipped.

## Async Execution

The primary way to run optimization. Returns an `OptimizationResult`. Import the result type
directly — don't guess the path:

```python
from traigent.api.types import OptimizationResult  # equivalently: traigent.OptimizationResult
```

See `traigent-analyze-results` for the full field reference.

> **Dry-run first.** Before a real (paid) run, always validate in mock mode and present a cost estimate to the user. See the `traigent` lifecycle skill for the mandatory dry-run-first / cost-approval workflow.
>
> ```python
> from traigent.testing import enable_mock_mode_for_quickstart
> enable_mock_mode_for_quickstart()
> results = await answer.optimize(max_trials=10, algorithm="grid")  # mock, no cost
> print(f"Mock pipeline OK: {len(results.trials)} trials, {len(results.failed_trials)} failed")
> # Estimate the REAL run's cost before approving. There is no `results.estimated_cost_usd`
> # accessor — the upper bound is (max_trials x dataset_size) LLM calls; price that against
> # your model's $/token, or set TRAIGENT_RUN_COST_LIMIT and let the run abort if it exceeds.
> max_trials, dataset_size = 10, 15        # your run's values
> print(f"Real run: up to {max_trials * dataset_size} LLM calls")
> ```
> Only proceed to the real run below after the user explicitly approves the cost.
>
> **Verify model IDs are live first.** Catalogs change — a delisted/renamed ID causes a 404 or a
> degraded, unpriced trial that wastes the run. Preflight with
> `traigent models --provider <p> --check <id>` (or the provider's live catalog endpoint). See
> the `traigent-setup-integrations` skill for multi-provider verification.

<!-- PROTECTED -->
> **Never mock the real run.** Mock/offline mode (`enable_mock_mode_for_quickstart()`,
> `TRAIGENT_MOCK_LLM`, `TRAIGENT_OFFLINE_MODE`) is for the DRY RUN only — never the run you're
> about to bill, score, or report as real. The mock LLM returns a constant response and near-zero
> cost, and that signature silently produces garbage scores if it leaks into what was supposed to
> be a real paid run. Before treating any run as real, verify it actually was:
>
> - `results.total_cost` must be a positive number. Mock runs cost ~0.
> - Per-trial outputs must vary. A constant mock response collapses every trial to the same,
>   uniform score.
>
> If a "real" run shows this signature (cost ~0, constant outputs, uniform scores), it was **not**
> real — do not report those numbers. Check that mock mode wasn't left enabled
> (`enable_mock_mode_for_quickstart()` sets process-local state that survives inside a long-lived
> interpreter/notebook — start a fresh interpreter for the real run) and that `TRAIGENT_MOCK_LLM` /
> `TRAIGENT_OFFLINE_MODE` are unset in the environment, then rerun.
<!-- /PROTECTED -->

```python
import traigent
import litellm  # pip install "traigent>=0.19" — the canonical runnable LLM call

@traigent.optimize(
    eval_dataset="qa_test.jsonl",
    objectives=["accuracy"],
    configuration_space={
        # Verify these IDs are live + priced before a real run (catalogs change).
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.1, 0.5, 0.9],
    },
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    resp = litellm.completion(
        model=cfg["model"],
        temperature=cfg["temperature"],
        messages=[{"role": "user", "content": question}],
    )
    return resp.choices[0].message.content

# Run optimization (real — only after dry-run approval)
results = await answer.optimize(max_trials=10)  # default algorithm="auto"
```

### optimize() Parameters

| Parameter | Type | Description |
|---|---|---|
| `algorithm` | `str \| None` | Algorithm: `"auto"` (default cloud smart optimizer), `"grid"`/`"random"` (local search). Named smart algorithms such as `"bayesian"`/`"optuna"` are connected-only (SDK 0.20.1+) — see below. Falls back to decorator setting. |
| `max_trials` | `int \| None` | Maximum number of trials to run. |
| `timeout` | `float \| None` | Maximum wall-clock time in seconds. |
| `save_to` | `str \| None` | Path to save results to disk. |
| `custom_evaluator` | `Callable \| None` | Override evaluator for this run. |
| `callbacks` | `list[Callable] \| None` | Progress tracking callbacks. |
| `configuration_space` | `dict \| None` | Override config space for this run. |
| `objectives` | `list[str] \| ObjectiveSchema \| None` | Override objectives for this run. |
| `warm_start_from` | `str \| None` | Identifier of a prior experiment run. Cloud sessions only: the SDK forwards it to backend session metadata, and the backend can reuse the referenced run's results to seed the search. No local/offline effect. |
| `cost_limit` | `float \| None` | Per-run cost cap in USD. Overrides `TRAIGENT_RUN_COST_LIMIT` for this call. A pre-run estimate over the limit raises `OptimizationError`; a mid-run budget hit returns partial results with `stop_reason="cost_limit"` (see cost handling below). |
| `**algorithm_kwargs` | `Any` | Algorithm-specific parameters (e.g., `parameter_order` for grid). |

To continue from a prior run, see the post-run flow (`traigent-analyze-guidance`).

## Sync Execution

For scripts or notebooks where you do not want to manage an async event loop.

```python
# Option 1: optimize_sync() convenience method
results = answer.optimize_sync(max_trials=10, algorithm="grid")

# Option 2: asyncio.run() wrapper
import asyncio
results = asyncio.run(answer.optimize(max_trials=10, algorithm="grid"))
```

`optimize_sync()` accepts the same parameters as `optimize()`. It creates and manages the event loop internally.

## Algorithm Selection

### Grid Search

Exhaustive search over all configurations in the config space. Deterministic and complete.

```python
results = await func.optimize(max_trials=24, algorithm="grid")

# Control iteration order with parameter_order
results = await func.optimize(
    algorithm="grid",
    parameter_order={"model": 0, "temperature": 1},  # model varies slowest
)
```

**Best for**: Small config spaces (under 50 combinations) where you want to test everything.

### Random Search

Samples configurations randomly from the config space. Good for large spaces where exhaustive search is impractical.

```python
results = await func.optimize(max_trials=20, algorithm="random")
```

**Best for**: Large config spaces, quick exploration, when you have a limited trial budget.

### Smart Algorithms (Bayesian / Optuna / TPE / CMA-ES / NSGA-II) — Connected-Only

> **Named smart selectors execute on connected runs since 0.20.1** (see version-matrix: `smart-selector-exec`). On an authenticated connected run, the supported names — `algorithm="bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, `"optuna_random"` — bind to the typed backend Optuna strategy and are serialized on session creation; unsupported smart names such as `"nsga2"`/`"cmaes"` fail fast before session creation with a capability message (Traigent/Traigent#1752, #1758; on 0.20.0 no named smart selector executed end-to-end). They never run locally on any version: with `offline=True` the decorator raises `ConfigurationError` at decoration time (*"requires managed optimization and cannot be used with offline=True"*), and the SDK's local optimizer registry rejects the names with `OptimizationError` (*"Smart optimization ('bayesian') runs in the Traigent cloud and is not available in the local SDK (which supports 'grid' and 'random')"*). `algorithm="auto"` (the default) remains the connected smart path when you do not need a specific strategy.

```python
# Connected-only — requires TRAIGENT_API_KEY and offline=False; on SDK 0.20.1+
# binds the named strategy server-side (fails on 0.20.0 and always with offline=True):
# results = await func.optimize(max_trials=30, algorithm="bayesian")

# Default connected smart path:
results = await func.optimize(max_trials=30, algorithm="auto")
```

### Quick Comparison

| Algorithm | Strategy | Config Space Size | Trial Budget | Where search runs |
|---|---|---|---|---|
| `"auto"` | Cloud smart default | Any | Any | Traigent cloud |
| `"grid"` | Exhaustive | Small (< 50) | Matches space size | Local SDK search |
| `"random"` | Sampling | Any | Limited | Local SDK search |
| `"bayesian"` / `"optuna"` / `"tpe"` / `"cmaes"` / `"nsga2"` | Named backend strategy | Any | Any | **Connected only, SDK 0.20.1+** (supported names bind server-side; `nsga2`/`cmaes` fail fast — see above) |

> ⚠️ **Local `default_config` consumes a `max_trials` slot.** In local SDK execution (`grid`,
> `random`, and `auto` when it resolves to local random), a supplied `default_config` runs as an
> extra baseline trial before optimizer suggestions and counts against `max_trials`. This bites
> hardest on `grid`: to cover an N-point grid, either omit `default_config` and set
> `max_trials = N`, or keep `default_config` and set `max_trials ≥ N + 1`; otherwise the last grid
> point is silently dropped. Backend-guided connected `auto` does not run `default_config` as a
> baseline trial today. (Field-observed on local SDK 0.21.0: a 2-point grid + `default_config` +
> `max_trials=2` evaluated only `[default, point-1]`.)

Results sync to the portal for every non-offline run, including `grid` and `random`; `offline=True` is the zero-egress path and does not sync results.

<!-- PROTECTED -->
## Cost Controls

Traigent tracks LLM API costs in real time and enforces budgets to prevent runaway spending.
<!-- /PROTECTED -->

### Cost Wiring Probe

Before any full paid run, do a tiny real optimization after mock validation: 1-2 dataset examples, minimal trials, and the cheapest candidate model. This is paid but should cost pennies, and it proves the billing and objective plumbing before scaling up. Check **both surfaces**:

- `results.total_cost` is `float | None`. `None` means cost tracking is unavailable. `0.0` with real calls means the model was unpriced, so the provider may bill while Traigent reports zero. Treat both as cost **not wired**.
- Each trial's `metrics` contains the declared objectives, especially an `accuracy`-labeled primary KPI by default, with real non-degenerate values. If all objective values are `0.0` or all are `1.0`, fix the evaluator/KPI wiring before the full run.

If cost or other KPIs are not picked up for custom services, self-hosted endpoints, or unknown models, fix in this order:

1. Use a model id LiteLLM can price, or map an alias with `litellm.model_alias_map`.
2. Supply custom per-token pricing with `TRAIGENT_CUSTOM_MODEL_PRICING_JSON` or `TRAIGENT_CUSTOM_MODEL_PRICING_FILE`. The JSON shape is `{"my-model": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}}`; `input`/`output` aliases are accepted, provider prefixes like `openai/` are normalized, and values must be finite non-negative floats. Pricing resolves in this order: LiteLLM, custom pricing, built-in fallback table, then `UnknownModelError`.
3. Report cost directly from the optimized function's per-trial metrics using `total_cost`, `cost`, or `input_cost` plus `output_cost`. This bypasses pricing tables and is the primary path for fully custom services.

Set `TRAIGENT_STRICT_COST_ACCOUNTING=true` when an unpriced model should fail loudly instead of reporting zero (see Strict Cost Accounting below). Full pricing details: `references/cost-management.md`.

### Setting a Cost Limit

Set the `TRAIGENT_RUN_COST_LIMIT` environment variable (in USD):

```bash
export TRAIGENT_RUN_COST_LIMIT=5.00  # $5 max per optimization run
```

The default limit is $2.00 per run.

### Handling a Cost Limit

**A cost limit does *not* surface through one exception — handle all of the paths below.** A common mistake is to catch only `CostLimitExceeded`; in the current SDK that handler never fires (see the note after the table).

| Surface | When it happens | How to handle |
|---|---|---|
| `OptimizationError` (**raised, pre-run**) | the *estimated* cost already exceeds the limit and the run wasn't pre-approved — raised **before any trial runs** | `except OptimizationError` — raise the limit, shrink the run, or set `TRAIGENT_COST_APPROVED=true` |
| `results.stop_reason == "cost_limit"` (**returned**) | the run hits the budget **mid-run**, stops, and **returns** partial results (no exception) | check `stop_reason` after a normal return |
| `CostLimitExceeded` (**not currently raised**) | exported & documented as the budget handler, but the current SDK never raises it (the mid-run stop returns `stop_reason="cost_limit"` instead) | keep in your `except` for forward-compatibility; do **not** rely on it as your only guard |

```python
from traigent.utils.exceptions import CostLimitExceeded, OptimizationError

try:
    results = await func.optimize(max_trials=100, algorithm="random")
except CostLimitExceeded as e:          # kept for forward-compat; not raised today
    print(f"Cost limit hit: ${e.accumulated:.2f} / ${e.limit:.2f}")
except OptimizationError as e:           # the pre-run "estimate > limit" decline
    print(f"Run declined before starting: {e}")
else:
    if getattr(results, "stop_reason", None) == "cost_limit":
        print("Budget reached mid-run; partial results returned.")
```

Notes:
- The pre-run decline's underlying exception is `OptimizationAborted`, which the SDK wraps into `OptimizationError` at the `optimize()` boundary — so `except OptimizationError` catches it there. Inside framework integrations (LangChain/LiteLLM) it may instead propagate **raw** as `OptimizationAborted`.
- The exact exception/return contract is being standardized upstream — see **Traigent/Traigent#1490**. Catching `OptimizationError` **and** `CostLimitExceeded`, **and** checking `results.stop_reason`, is robust across whichever way it resolves.

### Pre-Approving Costs

The `traigent` lifecycle skill mandates: **dry-run in mock mode first, present the cost estimate, then get explicit user approval before the real run.** Only pre-approve costs in automated pipelines where a human has already reviewed and approved the dry-run estimate. Never bypass this gate on a user's first run or when the config space has changed.

To skip the interactive cost approval handshake in an already-approved pipeline:

```bash
export TRAIGENT_COST_APPROVED=true
```

CI note: local/offline `optimize()` runs also require `TRAIGENT_RUN_APPROVED=1`; see
`traigent-debugging` for `OptimizationError: CI/CD Approval Required`.

### Quota & Run Sizing

Cost is not the only budget. Cloud/hybrid optimization is also **metered by plan quota**,
independent of dollars spent. Two dimensions are tracked per billing period (they reset
monthly):

- **`optimization_samples`** — examples evaluated across all sessions. This is the dimension
  that usually binds first. A run reserves roughly `max_trials × dataset_size` samples.
- **`optimization_trials`** — one optimization session counts as one trial.

A run is **admitted only when both dimensions have headroom**: it is rejected at
session-create if `current_usage + (max_trials × dataset_size)` would exceed the
`optimization_samples` limit (or if you are out of `optimization_trials`). On the free/hobby
tier the sample ceiling is small (500), so a few medium runs can exhaust it, after which new
runs are blocked (0 trials) until the monthly reset.

Before a large run:

1. **Check your current usage** on the portal billing/usage page (or your plan's usage
   summary) so you know how much of the `optimization_samples` budget remains.
2. **Size the run to fit**: pick `max_trials × dataset_size` so it lands under the remaining
   headroom. Shrink `max_trials`, use a smaller eval dataset, or split the run across periods
   if it would not fit. A blocked session-create can look like an input error — see the
   `traigent-debugging` skill ("session-create fails with quota") to recognize it.

> Quota is separate from the per-run dollar `cost_limit` above: staying under `cost_limit`
> does not guarantee you are under `optimization_samples`, and vice versa.

### Strict Cost Accounting

Fail fast if cost tracking cannot extract costs from LLM responses:

```bash
export TRAIGENT_STRICT_COST_ACCOUNTING=true
```

## Stop Conditions

Optimization can stop for several reasons. Check `results.stop_reason`:

| Stop Reason | Trigger |
|---|---|
| `"max_trials_reached"` | Hit the configured `max_trials` limit. |
| `"max_samples_reached"` | Hit the `max_total_examples` limit across all trials. |
| `"timeout"` | Exceeded the `timeout` duration. |
| `"cost_limit"` | Hit the `TRAIGENT_RUN_COST_LIMIT` budget. |
| `"optimizer"` | Algorithm exhausted the search space (e.g., grid search finished). |
| `"plateau"` | No improvement detected over recent trials. |
| `"user_cancelled"` | User cancelled or declined cost approval. |
| `"condition"` | A generic stop condition was triggered. |
| `"error"` | Optimization failed due to an exception. |

```python
results = await func.optimize(max_trials=20, algorithm="grid")

print(f"Stop reason: {results.stop_reason}")
print(f"Trials completed: {len(results.trials)}")
print(f"Best score: {results.best_score}")
```

## Parallel Execution

Run trials and/or examples concurrently using `ParallelConfig`.

```python
from traigent.config.parallel import ParallelConfig
from traigent.api.decorators import ExecutionOptions

@traigent.optimize(
    execution=ExecutionOptions(
        parallel_config=ParallelConfig(
            mode="parallel",
            trial_concurrency=2,    # Run 2 trials at the same time
            example_concurrency=4,  # Evaluate 4 examples concurrently per trial
        ),
    ),
    eval_dataset="large_dataset.jsonl",
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    import litellm  # pip install "traigent>=0.19"
    cfg = traigent.get_config()
    resp = litellm.completion(model=cfg["model"], messages=[{"role": "user", "content": query}])
    return resp.choices[0].message.content

results = await my_func.optimize(max_trials=10, algorithm="random")
```

### ParallelConfig Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `mode` | `"auto" \| "sequential" \| "parallel"` | `None` | Execution mode. `None` inherits from global config. |
| `trial_concurrency` | `int \| None` | `None` | Max concurrent trials. |
| `example_concurrency` | `int \| None` | `None` | Max concurrent examples per trial. |
| `thread_workers` | `int \| None` | `None` | Thread pool size. |

## Displaying Results

In SDK >=0.19, awaited `func.optimize()` and `func.optimize_sync()` already auto-print
the ranked trial table. Call `print_results_table()` only when you need to re-print
later, or when you need custom `objectives` / `config_space` display arguments.

```python
results = await func.optimize(max_trials=10, algorithm="grid")  # auto-prints the ranked table

# Optional: re-print later, or override the display metadata.
from traigent.utils.results_table import print_results_table

print_results_table(
    results,
    config_space=func.configuration_space,
    objectives=["accuracy"],   # match your objectives list
)
```

The table highlights the best trial with ★ and colors the best metric value per column.
`func.configuration_space` always reflects the decorator's current config space.

## Working with Results

`OptimizationResult` contains everything from the optimization run:

```python
results = await func.optimize(max_trials=10, algorithm="grid")

# Best configuration and score
print(results.best_config)     # {"model": "gpt-4o", "temperature": 0.5}
print(results.best_score)      # 0.92

# Run metadata
print(results.algorithm)       # "grid"
print(results.duration)        # 45.2 (seconds)
print(results.stop_reason)     # "max_trials_reached"
print(results.total_cost)      # 0.34 (USD, if tracked)
print(results.optimization_id) # "opt_abc123"

# Trial details (per-trial scores/costs live in trial.metrics; score mirrors the
# primary objective on SDKs after 0.21.3 — see version-matrix: score-relocation)
for trial in results.trials:
    print(f"Config: {trial.config}, Score: {trial.metrics.get('score')}")

# Derived properties
print(results.success_rate)       # 0.9 (fraction of successful trials)
print(len(results.successful_trials))  # 9
print(len(results.failed_trials))      # 1
```

### Applying the Best Config

After optimization, `func.apply_best_config(results)` locks in the winning configuration: subsequent calls to `func` use it automatically, `traigent.get_config()` inside the function returns it, and `func.current_config` exposes it from outside. Verify `results.best_score` against a threshold before applying — see `traigent-analyze-results` → Applying Best Config for the lifecycle table and the safety check. Applying the best config is not promotion; promotion requires candidate-vs-incumbent validation on the holdout slice (see `traigent-ci-safety-gate`).

### Confirm a Portal-Tracked Run Actually Synced

After a non-offline run, check `results.metadata.get("persistence_status")` — the SDK emits exactly
`"skipped"`, `"succeeded"`, `"degraded"`, or `"failed"` (never `"ok"`). If it's `"failed"`,
the backend finalize failed after retries and the portal session may be stuck `RUNNING` — re-check
the portal, don't assume the run synced. `"degraded"` has two cases, so check the metadata before
deciding: if `persistence_degraded_reason` is set (and `persistence_rejected` is not True), it's
benign rollup-lag — trial results *and* finalize synced (the portal link works), only summary
aggregates may lag, so keep the run and don't re-pay for a rerun. But if `persistence_rejected` is
True / `persistence_reason == "rejected"`, the backend actively **refused** the persistence (quota,
auth, or tenant) — inspect `persistence_rejection_reason` and treat it as a real problem, not benign.
Full detail: `traigent-analyze-results` → "Verify the Run Actually Persisted".

> **LiteLLM's `*_with_retries` helpers need `tenacity`.** If the decorated function calls
> `litellm.completion_with_retries()` / `acompletion_with_retries()`, know that LiteLLM imports
> `tenacity` lazily inside those helpers. On any SDK build before 0.21.3 (0.21.2 and earlier)
> `tenacity` is NOT in traigent's dependency closure, so in a clean install that retry path dies
> with `ModuleNotFoundError: tenacity`, and the failed call is scored 0, silently biasing the trial
> (field-hit on a real run; Traigent/Traigent#1824, fixed in 0.21.3 via #1825). Plain
> `litellm.completion(num_retries=)` is *not* affected — it uses LiteLLM's own internal retry loop
> and never imports `tenacity`. Traigent/Traigent#1825 (merged 2026-07-10) first declares
> `tenacity>=8.1.0` as a core dep: `tenacity` is bundled since 0.21.3 (0.21.2 and earlier lack it —
> see version-matrix: `tenacity-bundling`). On 0.21.2 and earlier, preflight
> `python -c "import tenacity"` before a paid run that relies on the `*_with_retries` helpers.

## Complete Example

End-to-end optimization from import to results:

```python
import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions
from traigent.config.parallel import ParallelConfig
from traigent.utils.exceptions import CostLimitExceeded, OptimizationError

def exact_match(output: str, expected: str) -> float:
    return 1.0 if output.strip() == expected.strip() else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="qa_test.jsonl",
        scoring_function=exact_match,
    ),
    execution=ExecutionOptions(
        parallel_config=ParallelConfig(
            mode="parallel",
            trial_concurrency=2,
            example_concurrency=4,
        ),
    ),
    objectives=["accuracy"],
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3, 0.7],
    },
)
def answer_question(question: str) -> str:
    import litellm  # pip install "traigent>=0.19"
    cfg = traigent.get_config()
    resp = litellm.completion(
        model=cfg["model"],
        temperature=cfg["temperature"],
        messages=[{"role": "user", "content": question}],
    )
    return resp.choices[0].message.content

async def main():
    # All three cost/failure surfaces from "Handling Cost Limit Exceptions" above.
    try:
        results = await answer_question.optimize(
            max_trials=6,
            algorithm="grid",
            timeout=300.0,
        )
    except CostLimitExceeded as e:  # kept for forward-compat; not raised today
        print(f"Budget exceeded: ${e.accumulated:.2f} / ${e.limit:.2f}")
        return
    except OptimizationError as e:  # pre-run "estimate > limit" decline, and run errors
        print(f"Run declined or failed: {e}")
        return

    if results.stop_reason == "cost_limit":
        print("Budget reached mid-run; results below are partial.")

    if results.best_score is None:
        # No successful trials — do NOT apply anything; report and stop.
        print(f"No trial succeeded (stop reason: {results.stop_reason}). "
              "Inspect the failed trials before spending more.")
        return

    # SDK >=0.19 auto-prints the ranked results table for awaited optimize().
    print(f"Best config: {results.best_config}")
    print(f"Best score:  {results.best_score}")
    print(f"Stop reason: {results.stop_reason}")
    print(f"Duration:    {results.duration:.1f}s")
    if results.total_cost:
        print(f"Total cost:  ${results.total_cost:.2f}")
    else:
        print("Total cost:  NOT TRACKED — wire cost before the next run (see Cost Wiring Probe)")

    # Apply and use in production
    answer_question.apply_best_config(results)
    answer = answer_question("What is the capital of France?")
    print(f"Answer: {answer}")

import asyncio
asyncio.run(main())
```

## See Also

- `references/algorithms.md` - Detailed algorithm comparison
- `references/parallel-config.md` - Full ParallelConfig reference
- `references/cost-management.md` - Cost enforcement details
- `traigent` - Lifecycle driver: dry-run-first / cost-approval mandate (read this before any real optimization run)
- `traigent-setup-quickstart` - Installation and first optimization with mock mode
- `traigent-setup-decorator` - Full `@traigent.optimize()` parameter reference
- `traigent-analyze-results` - **Next step:** read `best_config`/`best_score`, compare trials, extract the quality/cost/latency trade-off, and apply the best config after `optimize()` returns

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

### Fetch the live profile (when available)
At session or skill start, if a configured Traigent client is available, seed the profile from the
backend with the skill name:

```python
policy = None
try: policy = await client.get_interaction_policy(skill="<this skill>")
except Exception: pass
```

Treat the returned `profile` as the STARTING seed: its control/expertise/pace axes plus
`question_budget`, `options_max`, and `jargon_level` replace the static defaults below. Explicit user
corrections in-conversation ALWAYS override the seed. If the call is unavailable or
`fallback_policy="static_v1"`, simply use the static defaults below; the SDK already fails soft.

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
