# Execution Modes Reference

`ExecutionOptions` is a Pydantic model that controls where and how optimization runs execute.

```python
from traigent.api.decorators import ExecutionOptions
```

## ExecutionOptions Fields

### Core Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `execution_mode` | `str` | `"edge_analytics"` | Where to run: `"edge_analytics"`, `"cloud"`, or `"hybrid"`. |
| `local_storage_path` | `str \| None` | `None` | Directory path for local result storage. |
| `minimal_logging` | `bool` | `True` | Minimize logging output during optimization. |
| `parallel_config` | `ParallelConfig \| dict \| None` | `None` | Parallel execution settings. See ParallelConfig section. |
| `privacy_enabled` | `bool \| None` | `None` | Enable privacy-preserving mode (no raw data sent to cloud). |
| `max_total_examples` | `int \| None` | `None` | Cap total examples evaluated across all trials. |
| `samples_include_pruned` | `bool` | `True` | Whether pruned trials count toward sample limits. |
| `cloud_fallback_policy` | `str \| None` | `None` | Behavior on cloud execution failure: `"auto"`, `"warn"`, or `"never"`. |

### Repetition Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `reps_per_trial` | `int` | `1` | Number of times to repeat each configuration. **Requires Traigent Enterprise** — on the standard tier any value other than `1` is rejected at `ExecutionOptions` construction (`reps_per_trial != 1`). |
| `reps_aggregation` | `str` | `"mean"` | How to aggregate metrics across repetitions: `"mean"`, `"median"`, `"min"`, or `"max"` (applies only when `reps_per_trial > 1` on Enterprise). |

### Hybrid API Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `hybrid_api_endpoint` | `str \| None` | `None` | URL of the hybrid API server. |
| `tunable_id` | `str \| None` | `None` | Identifier for this tunable in the hybrid API. |
| `hybrid_api_transport` | `Any \| None` | `None` | Custom transport instance for the hybrid API. |
| `hybrid_api_transport_type` | `str` | `"auto"` | Transport type: `"auto"`, `"http"`, `"grpc"`, etc. |
| `hybrid_api_batch_size` | `int` | `1` | Batch size for hybrid API requests. |
| `hybrid_api_batch_parallelism` | `int` | `1` | Number of parallel batches. |
| `hybrid_api_keep_alive` | `bool` | `True` | Keep the hybrid API connection alive between trials. |
| `hybrid_api_heartbeat_interval` | `float` | `30.0` | Heartbeat interval in seconds. |
| `hybrid_api_timeout` | `float \| None` | `None` | Request timeout for hybrid API calls. |
| `hybrid_api_auth_header` | `str \| None` | `None` | Authorization header value for hybrid API. |
| `hybrid_api_auto_discover_tvars` | `bool` | `False` | Automatically discover tunable variables from the hybrid API. |

## Execution Modes Explained

### Edge Analytics (Default)

Optimization runs entirely on your local machine. Only anonymized analytics metadata (trial counts, scores, timing) is sent to the Traigent cloud for dashboards and experiment tracking. Raw data, prompts, and model outputs never leave your environment.

```python
@traigent.optimize(
    execution=ExecutionOptions(
        execution_mode="edge_analytics",
        local_storage_path="./results",
        privacy_enabled=True,
    ),
    configuration_space={"model": ["gpt-3.5-turbo", "gpt-4"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

**When to use**: Most use cases. Keeps data local, still get cloud dashboards.

### Cloud

Full remote execution. The Traigent cloud orchestrates trials, manages compute, and stores results. Requires authentication and network connectivity.

```python
@traigent.optimize(
    execution=ExecutionOptions(execution_mode="cloud"),
    configuration_space={"model": ["gpt-3.5-turbo", "gpt-4"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

**When to use**: When you want centralized orchestration, team collaboration, or need to run optimization on cloud infrastructure.

### Hybrid

Splits execution between local and cloud. Trials run locally, but the cloud coordinates configuration selection, tracks experiments, and provides advanced analytics.

```python
@traigent.optimize(
    execution=ExecutionOptions(
        execution_mode="hybrid",
        hybrid_api_endpoint="https://api.traigent.io/v1/hybrid",
        hybrid_api_batch_size=4,
        hybrid_api_batch_parallelism=2,
    ),
    configuration_space={"model": ["gpt-3.5-turbo", "gpt-4"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

**When to use**: When you need cloud-level coordination but want trial execution to happen locally (e.g., for data privacy or custom infrastructure).

### Cloud Fallback Policy

Controls what happens when cloud or hybrid execution fails:

| Policy | Behavior |
|---|---|
| `"auto"` | Silently falls back to local optimization on failure. |
| `"warn"` | Falls back to local optimization but logs a warning. |
| `"never"` | Re-raises the exception. No fallback. |

## ParallelConfig Integration

Pass a `ParallelConfig` to run trials and/or examples in parallel:

```python
from traigent.config.parallel import ParallelConfig

@traigent.optimize(
    execution=ExecutionOptions(
        parallel_config=ParallelConfig(
            mode="parallel",
            trial_concurrency=2,
            example_concurrency=4,
        ),
    ),
    configuration_space={"model": ["gpt-3.5-turbo", "gpt-4"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

You can also pass it as a dictionary:

```python
@traigent.optimize(
    execution=ExecutionOptions(
        parallel_config={
            "mode": "parallel",
            "trial_concurrency": 2,
            "example_concurrency": 4,
        },
    ),
    configuration_space={"model": ["gpt-3.5-turbo", "gpt-4"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

## JavaScript / TypeScript Applications

To optimize an LLM application written in JavaScript/TypeScript, use the native
**`@traigent/sdk`** (see the `traigent-js` skill) rather than the Python SDK. The
former in-process "JS bridge" `ExecutionOptions` fields (`runtime`, `js_module`,
`js_function`, `js_timeout`, `js_parallel_workers`) are not part of the `0.12.0`
Python `ExecutionOptions` — it is `extra="forbid"`, so passing them raises a
pydantic `ValidationError` at construction.

## Repetitions for Statistical Stability

LLM outputs are non-deterministic. On **Traigent Enterprise**, `reps_per_trial` repeats
each configuration multiple times and aggregates the results. On the standard tier
`reps_per_trial` must stay `1` (any other value is rejected at construction), so the
example below is Enterprise-only:

```python
# contract: skip
# Requires Traigent Enterprise (reps_per_trial > 1 is rejected on the standard tier)
@traigent.optimize(
    execution=ExecutionOptions(
        reps_per_trial=5,          # Run each config 5 times
        reps_aggregation="median", # Use median score (robust to outliers)
    ),
    configuration_space={"temperature": [0.0, 0.3, 0.7, 1.0]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(temperature=cfg["temperature"], prompt=query)
```

Aggregation options:

| Method | Use When |
|---|---|
| `"mean"` | Default. Good for normally distributed scores. |
| `"median"` | Robust to outliers. Good for noisy evaluations. |
| `"min"` | Worst-case analysis. Conservative. |
| `"max"` | Best-case analysis. Optimistic. |
