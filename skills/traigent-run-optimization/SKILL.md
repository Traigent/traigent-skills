---
name: traigent-run-optimization
description: "Run Traigent optimization: async/sync execution, algorithm selection, cost limits, stop conditions, and parallel trials. Use when calling func.optimize() or optimize_sync(), choosing algorithms (auto/grid/random/bayesian/optuna), setting max_trials or cost_limit, configuring parallel execution, or handling CostLimitExceeded."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.1"
---

# Running Traigent Optimization

## When to Use

Use this skill after you have decorated a function with `@traigent.optimize()` and need to:

- Run optimization (async or sync)
- Choose an algorithm (auto, grid, random, bayesian, optuna)
- Set trial limits, timeouts, or cost budgets
- Configure parallel trial execution
- Handle cost limit exceptions
- Interpret stop reasons and results

## Async Execution

The primary way to run optimization. Returns an `OptimizationResult`.

> **Dry-run first.** Before a real (paid) run, always validate in mock mode and present a cost estimate to the user. See the `traigent` lifecycle skill for the mandatory dry-run-first / cost-approval workflow.
>
> ```python
> from traigent.testing import enable_mock_mode_for_quickstart
> enable_mock_mode_for_quickstart()
> results = await answer.optimize(max_trials=10, algorithm="grid")  # mock, no cost
> print(results.estimated_cost_usd)  # review estimate before approving
> ```
> Only proceed to the real run below after the user explicitly approves the cost.

```python
import traigent

@traigent.optimize(
    eval_dataset="qa_test.jsonl",
    objectives=["accuracy"],
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.1, 0.5, 0.9],
    },
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], temperature=cfg["temperature"], prompt=question)

# Run optimization (real — only after dry-run approval)
results = await answer.optimize(max_trials=10)  # default algorithm="auto"
```

### optimize() Parameters

| Parameter | Type | Description |
|---|---|---|
| `algorithm` | `str \| None` | Algorithm: `"auto"` (default cloud smart optimizer), `"grid"`/`"random"` (local search), or cloud-only smart algorithms such as `"bayesian"`/`"optuna"`. Falls back to decorator setting. |
| `max_trials` | `int \| None` | Maximum number of trials to run. |
| `timeout` | `float \| None` | Maximum wall-clock time in seconds. |
| `save_to` | `str \| None` | Path to save results to disk. |
| `custom_evaluator` | `Callable \| None` | Override evaluator for this run. |
| `callbacks` | `list[Callable] \| None` | Progress tracking callbacks. |
| `configuration_space` | `dict \| None` | Override config space for this run. |
| `objectives` | `list[str] \| ObjectiveSchema \| None` | Override objectives for this run. |
| `cost_limit` | `float \| None` | Per-run cost cap in USD. Overrides `TRAIGENT_RUN_COST_LIMIT` for this call. Raises `CostLimitExceeded` when hit. |
| `**algorithm_kwargs` | `Any` | Algorithm-specific parameters (e.g., `parameter_order` for grid). |

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

### Bayesian Optimization *(cloud only)*

> **Requires a Traigent cloud connection.** `algorithm="bayesian"` (and the other smart optimizers) run in the Traigent cloud, not the local SDK. With `offline=True` or no Traigent cloud connection, it raises `OptimizationError`. Use `"grid"` or `"random"` for local search.

Uses a surrogate model to guide the search toward promising configurations.

```python
results = await func.optimize(max_trials=30, algorithm="bayesian")
```

**Best for**: Medium to large config spaces with continuous parameters (cloud runs).

### Optuna *(cloud only)*

> **Requires a Traigent cloud connection.** `algorithm="optuna"` (and the other smart optimizers) run in the Traigent cloud, not the local SDK. With `offline=True` or no Traigent cloud connection, it raises `OptimizationError`. Use `"grid"` or `"random"` for local search.

Cloud-only access to advanced Optuna-style optimization with features like pruning and multi-objective optimization.

```python
results = await func.optimize(max_trials=50, algorithm="optuna")
```

**Best for**: Advanced users running in the Traigent cloud who need Optuna-specific features or very large search spaces.

### Quick Comparison

| Algorithm | Strategy | Config Space Size | Trial Budget | Where search runs |
|---|---|---|---|---|
| `"auto"` | Cloud smart default | Any | Any | Traigent cloud |
| `"grid"` | Exhaustive | Small (< 50) | Matches space size | Local SDK search |
| `"random"` | Sampling | Any | Limited | Local SDK search |
| `"bayesian"` | Model-guided | Medium-Large | 15-100 | Cloud only |
| `"optuna"` | Advanced sampling | Large | 30+ | Cloud only |

Results sync to the portal for every non-offline run, including `grid` and `random`; `offline=True` is the zero-egress path and does not sync results.

<!-- PROTECTED -->
## Cost Controls

Traigent tracks LLM API costs in real time and enforces budgets to prevent runaway spending.
<!-- /PROTECTED -->

### Setting a Cost Limit

Set the `TRAIGENT_RUN_COST_LIMIT` environment variable (in USD):

```bash
export TRAIGENT_RUN_COST_LIMIT=5.00  # $5 max per optimization run
```

The default limit is $2.00 per run.

### Handling CostLimitExceeded

When the cost limit is reached, Traigent raises `CostLimitExceeded`:

```python
from traigent.utils.exceptions import CostLimitExceeded

try:
    results = await func.optimize(max_trials=100, algorithm="bayesian")
except CostLimitExceeded as e:
    print(f"Cost limit hit: ${e.accumulated:.2f} / ${e.limit:.2f}")
    # Optimization stopped but partial results may be available
```

The exception has two attributes:
- `e.accumulated` (float) - Total cost accumulated before the limit was hit.
- `e.limit` (float) - The configured cost limit.

### Pre-Approving Costs

The `traigent` lifecycle skill mandates: **dry-run in mock mode first, present the cost estimate, then get explicit user approval before the real run.** Only pre-approve costs in automated pipelines where a human has already reviewed and approved the dry-run estimate. Never bypass this gate on a user's first run or when the config space has changed.

To skip the interactive cost approval handshake in an already-approved pipeline:

```bash
export TRAIGENT_COST_APPROVED=true
```

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
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)

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

Always call `print_results_table()` after `func.optimize()` to show a green-highlighted
trial results table with per-config scores. Skip only if the user explicitly says no.

```python
from traigent.utils.results_table import print_results_table

results = await func.optimize(max_trials=10, algorithm="grid")

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

# Trial details (per-trial scores/costs live in trial.metrics, not on the trial)
for trial in results.trials:
    print(f"Config: {trial.config}, Score: {trial.metrics.get('score')}")

# Derived properties
print(results.success_rate)       # 0.9 (fraction of successful trials)
print(len(results.successful_trials))  # 9
print(len(results.failed_trials))      # 1
```

### Applying the Best Config

After optimization, lock in the best configuration for production use:

```python
results = await func.optimize(max_trials=10, algorithm="grid")
func.apply_best_config(results)

# Now calling func uses the best config automatically
answer = func("What is Python?")

# The config is accessible via get_config() inside the function
# and via func.current_config from outside
print(func.current_config)  # {"model": "gpt-4o", "temperature": 0.5}
```

## Complete Example

End-to-end optimization from import to results:

```python
import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions
from traigent.config.parallel import ParallelConfig
from traigent.utils.exceptions import CostLimitExceeded
from traigent.utils.results_table import print_results_table

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
    cfg = traigent.get_config()
    return call_llm(
        model=cfg["model"],
        temperature=cfg["temperature"],
        prompt=question,
    )

async def main():
    try:
        results = await answer_question.optimize(
            max_trials=6,
            algorithm="grid",
            timeout=300.0,
        )
    except CostLimitExceeded as e:
        print(f"Budget exceeded: ${e.accumulated:.2f} / ${e.limit:.2f}")
        return

    print_results_table(
        results,
        config_space=answer_question.configuration_space,
        objectives=["accuracy"],
    )

    print(f"Best config: {results.best_config}")
    print(f"Best score:  {results.best_score}")
    print(f"Stop reason: {results.stop_reason}")
    print(f"Duration:    {results.duration:.1f}s")
    print(f"Total cost:  ${results.total_cost:.2f}" if results.total_cost else "")

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
- `traigent-quickstart` - Installation and first optimization with mock mode
- `traigent-decorator-setup` - Full `@traigent.optimize()` parameter reference

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
