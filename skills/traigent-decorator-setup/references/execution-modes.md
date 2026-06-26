# Optimization Execution Reference: `algorithm`, `offline`, and `ExecutionOptions`

Where and how an optimization run executes is controlled by two top-level knobs on
`@traigent.optimize(...)` — `algorithm` and `offline` — plus the advanced `ExecutionOptions`
bundle.

```python
import traigent
from traigent.api.decorators import ExecutionOptions
```

## The two execution knobs

| Knob | Type | Default | Description |
|---|---|---|---|
| `algorithm` | `str` | `"auto"` | `"auto"` uses the Traigent **cloud smart optimizer** while your trials run in your environment. `"grid"`/`"random"` run local search in the SDK. Smart optimizers (`"bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, `"optuna_random"`, `"optuna_grid"`, `"optuna_cmaes"`, `"optuna_nsga2"`, `"nsga2"`, `"cmaes"`, `"nsgaii"`, `"nsga_ii"`, `"cma_es"`) are **cloud-only**. Unknown names are rejected. |
| `offline` | `bool` | `False` | `True` forces a fully local run with **zero backend egress** and no portal sync. |

```python
@traigent.optimize(
    algorithm="auto",     # default cloud smart optimizer
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

## How each choice behaves

- **`algorithm="auto"` (default).** The Traigent cloud smart optimizer proposes each configuration and learns across runs; **your agent and your LLM calls run in your environment**. Results sync to the portal.
- **`algorithm="grid"` / `"random"` — local search.** The search runs in the SDK. Results still sync to the portal unless `offline=True`.
- **Smart algorithms — cloud-only.** `"bayesian"`, `"optuna"`, and related smart optimizers require a Traigent cloud connection. Do not present them as local options.
- **`offline=True` — zero egress.** Nothing leaves your machine and results do not sync to the portal. Use this for air-gapped or strict-no-network runs.

> **Data flow.** Portal-synced runs send configuration IDs and numeric metrics, not dataset example inputs, prompts, or outputs. For zero outbound traffic, use `offline=True`.

## Result sync

Results sync to the Traigent portal in every non-offline run, including local `grid` and
`random` search. `offline=True` disables backend egress and portal sync.

## Optimizing an external service (HTTP / MCP)

To optimize an agent exposed behind an external HTTP/MCP endpoint, put the service call in
your decorated function or in an `EvaluationOptions(custom_evaluator=...)` implementation.
Keep the search strategy configured with `algorithm` and `offline`.

```python
from traigent.api.decorators import EvaluationOptions

def score_remote_response(func, config, example):
    # Call your HTTP/MCP service here and return the evaluator result your app expects.
    return call_remote_evaluator(func, config, example)

@traigent.optimize(
    evaluation=EvaluationOptions(custom_evaluator=score_remote_response),
    algorithm="auto",
    configuration_space={"temperature": [0.0, 0.3, 0.7]},
)
def my_remote_agent(query: str) -> str: ...
```

## `ExecutionOptions` advanced fields

`ExecutionOptions` carries `algorithm` and `offline` plus the advanced execution settings:

| Field | Type | Default | Description |
|---|---|---|---|
| `algorithm` | `str` | `"auto"` | Same as the top-level knob above. |
| `offline` | `bool` | `False` | Same as the top-level knob above. |
| `local_storage_path` | `str \| None` | `None` | Directory for local result storage. |
| `minimal_logging` | `bool` | `True` | Minimize logging output during optimization. |
| `parallel_config` | `ParallelConfig \| dict \| None` | `None` | Parallel execution settings (see below). |
| `max_total_examples` | `int \| None` | `None` | Cap total examples evaluated across all trials. |
| `samples_include_pruned` | `bool` | `True` | Whether pruned trials count toward sample limits. |

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
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
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
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

## JavaScript / TypeScript Applications

To optimize an LLM application written in JavaScript/TypeScript, use the native
**`@traigent/sdk`** (see the `traigent-js` skill) rather than the Python SDK. The former
in-process JavaScript runtime `ExecutionOptions` fields are not part of the Python `ExecutionOptions`
— it is `extra="forbid"`, so passing them raises a pydantic `ValidationError` at construction.
