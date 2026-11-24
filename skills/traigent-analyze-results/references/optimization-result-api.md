# OptimizationResult and TrialResult API Reference

## OptimizationResult

The `OptimizationResult` dataclass is returned by `func.optimize()` and contains all data from an optimization run.

### Fields

| Field | Type | Description |
|---|---|---|
| `trials` | `list[TrialResult]` | All trial results from the optimization run, in execution order. |
| `best_config` | `dict[str, Any] \| None` | The selected configuration, or `None` when no eligible trial produced a winner. `{}` is not unique to one failure mode: it can mean an objectives-free run, an eligible winner whose config is empty, or strict-evidence mode with no certified winner. Diagnose it from `results.metadata["session_summary"]` (`reason` / `reason_code`, when present) and the declared objectives; guard consumption with `if not results.best_config`. |
| `best_score` | `float \| None` | The best objective score achieved. `None` when no trial produced a valid, rankable score. |
| `optimization_id` | `str` | Unique identifier for this optimization run. |
| `duration` | `float` | Total wall-clock time in seconds for the entire optimization. |
| `convergence_info` | `dict[str, Any]` | Dictionary with convergence statistics (see convergence-patterns.md for fields). |
| `status` | `OptimizationStatus` | Final status of the optimization. One of: `NOT_STARTED`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `UNKNOWN`. |
| `objectives` | `list[str]` | List of objective metric names being optimized (e.g., `["accuracy"]`). |
| `algorithm` | `str` | Name of the optimization algorithm used. |
| `timestamp` | `datetime` | When the optimization completed. |
| `metadata` | `dict[str, Any]` | Additional metadata from the optimization run. Default: `{}`. |
| `total_cost` | `float \| None` | Total API cost incurred in USD. `None` if cost tracking is not available, and (SDK 0.32.0+) when any trial's cost is unmeasured: the known spend is then a lower bound in `metrics["cost_floor_usd"]`, with the count in `metrics["cost_unmeasured_trials"]`. |
| `total_tokens` | `int \| None` | Total tokens consumed across all trials. `None` if token tracking is not available. |
| `metrics` | `dict[str, Any]` | Aggregated metrics across all trials. Default: `{}`. |
| `stop_reason` | `StopReason \| None` | Why the optimization stopped. See StopReason values below. |
| `best_config_margin` | `dict[str, Any] \| None` | Winner-vs-best-distinct-runner-up paired margin qualifying `best_config` (SDK >= 0.26.0): `verdict` (`"clear"` / `"statistical_tie"` / `"na"`), `delta`, `ci95`, `p_value`, `n_shared_examples`, `runner_up`, `n_configs`, `effective_alpha` (Bonferroni over `n_configs - 1`), optional `reason`. `None` when there is no runner-up. |

### Properties

| Property | Return Type | Description |
|---|---|---|
| `experiment_stats` | `ExperimentStats` | Lazy-loaded, memoized aggregate statistics for the full experiment. Includes `total_duration`, `total_cost`, `unique_configurations`, `trial_counts`, `average_trial_duration`, `cost_per_configuration`, `success_rate`, `cost_unmeasured_trials`, `cost_lower_bound`. |
| `successful_trials` | `list[TrialResult]` | Filtered list of trials with `status == COMPLETED`. |
| `failed_trials` | `list[TrialResult]` | Filtered list of trials with `status == FAILED`. |
| `success_rate` | `float` | Ratio of successful trials to total trials. Returns `0.0` if no trials exist. |
| `best_metrics` | `dict[str, float]` | Full metrics dict from the best-scoring trial. Returns `{}` if no trials exist. |
| `example_matrix` | `dict[str, Any]` | Per-example × per-trial outcome matrix built in memory from each trial's `example_results`; `examples` is empty when the run captured no per-example detail. |
| `eval_audit` | `EvalAudit \| None` | Opt-in, zero-cost dataset-defect audit over `example_matrix` (never-correct, token-leak, cross-family consensus-on-wrong): `flagged` (`EvalAuditFlag`: `example_id`, `detectors`, `suggested_answer`), `summary`, `scored`. `None` when no per-example detail was captured or fewer than two configurations ran. |

### Usage

```python
results = func.optimize_sync()

# Direct field access
print(results.best_config)       # {"model": "gpt-4o", "temperature": 0.0}
print(results.best_score)        # 0.92
print(results.optimization_id)   # "opt-a1b2c3d4"
print(results.duration)          # 45.3
print(results.status)            # OptimizationStatus.COMPLETED
print(results.stop_reason)       # "max_trials_reached"
print(results.total_cost)        # 0.0234
print(results.total_tokens)      # 15420

# Computed properties
print(results.success_rate)      # 0.8
print(results.best_metrics)      # {"accuracy": 0.92, "latency": 800.0}  # latency in ms on SDKs after 0.22.0 (see version-matrix: latency-unit)
print(len(results.successful_trials))  # 8
print(len(results.failed_trials))      # 2

# Experiment stats (lazy-loaded)
stats = results.experiment_stats
print(stats.total_duration)           # 45.3
print(stats.total_cost)              # 0.0234
print(stats.unique_configurations)    # 6
print(stats.trial_counts)            # {"total": 10, "completed": 8, "failed": 2, ...}
print(stats.average_trial_duration)   # 4.53
print(stats.cost_per_configuration)   # 0.0039
print(stats.success_rate)            # 0.8
```

---

## TrialResult

The `TrialResult` dataclass represents the outcome of a single optimization trial.

### Fields

| Field | Type | Description |
|---|---|---|
| `trial_id` | `str` | Unique identifier for this trial. |
| `config` | `dict[str, Any]` | The configuration used for this trial (e.g., `{"model": "gpt-4o", "temperature": 0.5}`). |
| `metrics` | `dict[str, float]` | Metric values produced by this trial (e.g., `{"accuracy": 0.85, "latency": 1200.0}` — the bare `latency` metric is **milliseconds** on SDKs after 0.22.0; see version-matrix: `latency-unit`). |
| `status` | `TrialStatus` | Status of this trial. One of: `NOT_STARTED`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `PRUNED`, `UNKNOWN`. |
| `duration` | `float` | Wall-clock execution time for this trial in seconds. |
| `timestamp` | `datetime` | When this trial was executed. |
| `error_message` | `str \| None` | Error message if the trial failed. `None` for successful trials. |
| `metadata` | `dict[str, Any]` | Additional metadata (e.g., example-level results, provider info). Default: `{}`. |

### Properties

| Property | Return Type | Description |
|---|---|---|
| `is_successful` | `bool` | `True` if `status == TrialStatus.COMPLETED`. |

### Methods

| Method | Signature | Description |
|---|---|---|
| `get_metric` | `get_metric(name: str, default: float \| None = None) -> float \| None` | Safely retrieve a metric value by name, returning `default` if the metric is not present. |

### Usage

```python
for trial in results.trials:
    # Field access
    print(trial.trial_id)       # "trial-001"
    print(trial.config)         # {"model": "gpt-4o-mini", "temperature": 0.3}
    print(trial.metrics)        # {"accuracy": 0.85, "latency": 1200.0}  # ms on SDKs after 0.22.0 (see version-matrix: latency-unit)
    print(trial.status)         # TrialStatus.COMPLETED
    print(trial.duration)       # 3.7
    print(trial.timestamp)      # datetime(2024, 1, 15, 10, 30, 0)
    print(trial.error_message)  # None (or error string for failed trials)
    print(trial.metadata)       # {}

    # Property
    if trial.is_successful:
        # Method
        accuracy = trial.get_metric("accuracy")          # 0.85
        latency = trial.get_metric("latency_ms", 0.0)    # 0.0 (not present, returns default)
```

---

## StopReason Values

`StopReason` is a string literal type. Possible values:

| Value | Description |
|---|---|
| `"max_trials_reached"` | The configured `max_trials` limit was reached. |
| `"max_samples_reached"` | The maximum number of samples/examples was reached. |
| `"timeout"` | The optimization exceeded its timeout duration. |
| `"cost_limit"` | The accumulated per-run cost reached the configured budget; the completed trials are kept and returned. |
| `"execution_budget"` | A shared cumulative `ExecutionBudget` (cost, examples, or deadline) was exhausted (SDK >= 0.26.0); reported instead of `"cost_limit"`, detail in `metadata["execution_budget"]`. |
| `"metric_limit"` | A soft cumulative metric limit was hit. |
| `"optimizer"` | The optimizer decided to stop (e.g., configuration space exhausted). |
| `"plateau"` | A plateau was detected (no improvement over recent trials). |
| `"convergence"` | A built-in convergence condition triggered. |
| `"semantic_saturation"` | Per-example quality and continuous objectives saturated; detail in `metadata["semantic_saturation"]`. |
| `"safety_constraint"` | An in-run `safety_constraints` halt (SDK >= 0.28.0). On SDK 0.31.0+ it means a violation: observed compliance is below the required rate. On 0.28.0-0.30.0 it also fired when the evidence was too thin to prove the constraint. Not a trial filter or a safety verdict. |
| `"safety_constraint_insufficient_evidence"` | An in-run `safety_constraints` halt where the constraint is not proven and not violated: observed compliance meets the required rate, but the confidence lower bound does not prove it (SDK >= 0.31.0). The run halts fail-closed. |
| `"no_usage_captured"` | A strict cost-objective run stopped after its first successful trial that captured no LLM usage (SDK >= 0.31.0); new trials are not scheduled, trials in flight may finish. On the strict default the call then raises `UnknownModelError` with the finished trials on `err.result`. |
| `"user_cancelled"` | The user cancelled the optimization or declined a cost approval prompt. |
| `"condition"` | A generic stop condition was triggered. |
| `"error"` | The optimization failed due to an unrecoverable exception. |
| `"vendor_error"` | A provider-side error occurred (rate limit, quota exceeded, service unavailable). |
| `"network_error"` | A network connectivity failure prevented further trials. |

---

## OptimizationStatus Enum

```python
from traigent.api.types import OptimizationStatus

OptimizationStatus.NOT_STARTED   # "not_started"
OptimizationStatus.PENDING       # "pending"
OptimizationStatus.RUNNING       # "running"
OptimizationStatus.COMPLETED     # "completed"
OptimizationStatus.FAILED        # "failed"
OptimizationStatus.CANCELLED     # "cancelled"
OptimizationStatus.UNKNOWN       # "unknown"
```

## TrialStatus Enum

```python
from traigent.api.types import TrialStatus

TrialStatus.NOT_STARTED  # "not_started"
TrialStatus.PENDING      # "pending"
TrialStatus.RUNNING      # "running"
TrialStatus.COMPLETED    # "completed"
TrialStatus.FAILED       # "failed"
TrialStatus.CANCELLED    # "cancelled"
TrialStatus.PRUNED       # "pruned"
TrialStatus.UNKNOWN      # "unknown"
```

---

## ExperimentStats

The `ExperimentStats` dataclass is accessible via `results.experiment_stats` and provides aggregate statistics.

### Fields

| Field | Type | Description |
|---|---|---|
| `total_duration` | `float` | Total wall-clock time in seconds. |
| `total_cost` | `float \| None` | Total API cost in USD. `None` (SDK 0.31.0+) when any trial's cost is unmeasured: the known spend is then only a lower bound in `cost_lower_bound`, with the count in `cost_unmeasured_trials`. |
| `unique_configurations` | `int` | Number of distinct configurations tested. |
| `trial_counts` | `dict[str, int]` | Breakdown by status: `total`, `completed`, `failed`, `cancelled`, `running`, `pending`, `not_started`, `exceptions`. |
| `average_trial_duration` | `float \| None` | Mean trial duration in seconds. `None` if no valid durations. |
| `cost_per_configuration` | `float \| None` | Average cost per unique configuration. `None` if no configurations, or when `total_cost` is `None`. |
| `success_rate` | `float \| None` | Ratio of successful trials to total. `None` if no trials. |
| `error_message` | `str \| None` | Error message if stats computation failed. |
| `cost_unmeasured_trials` | `int` | Number of trials whose cost was not measured (SDK 0.31.0+). Default `0`. |
| `cost_lower_bound` | `float \| None` | Known spend when `total_cost` is withheld for unmeasured trials (SDK 0.31.0+). `None` when every trial's cost is measured, or when the known spend floor is `0`. |

### to_dict()

```python
stats_dict = results.experiment_stats.to_dict()
# Returns all fields as a plain dictionary for logging or serialization.
```
