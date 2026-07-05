# Optimization Execution Reference: `algorithm`, `offline`, and `ExecutionOptions`

Where and how an optimization run executes is controlled by two top-level knobs on
`@traigent.optimize(...)` — `algorithm` and `offline` — plus the advanced `ExecutionOptions`
bundle.

```python
import litellm
import traigent
from traigent.api.decorators import ExecutionOptions

def prompt_model(prompt: str, *, model: str) -> str:
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
```

## The two execution knobs

| Knob | Type | Default | Description |
|---|---|---|---|
| `algorithm` | `str` | `"auto"` | `"auto"` uses the Traigent **cloud smart optimizer** while your trials run in your environment. `"grid"`/`"random"` run local search in the SDK. Named smart selectors (`"bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, `"optuna_random"`, `"optuna_grid"`, `"optuna_cmaes"`, `"optuna_nsga2"`, `"nsga2"`, `"cmaes"`, `"nsgaii"`, `"nsga_ii"`, `"cma_es"`) validate as known names but are **not yet executable end-to-end**: `offline=True` raises `ConfigurationError`, the local registry raises `OptimizationError`, and connected typed runs self-abort before backend guidance because the SDK does not execute/transmit the named selector (Traigent/Traigent#1752). Unknown names are rejected. |
| `offline` | `bool` | `False` | `True` forces a fully local run with **zero backend egress** and no portal sync. |

```python
@traigent.optimize(
    algorithm="auto",     # default cloud smart optimizer
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(query, model=cfg["model"])
```

## How each choice behaves

- **`algorithm="auto"` (default).** The Traigent cloud smart optimizer proposes each configuration and learns across runs; **your agent and your LLM calls run in your environment**. Results sync to the portal.
- **`algorithm="grid"` / `"random"` — local search.** The search runs in the SDK. Results still sync to the portal unless `offline=True`.
- **Named smart selectors — not yet executable end-to-end.** `"bayesian"`, `"optuna"`, and related selector names fail before any trial runs: `ConfigurationError` at decoration time with `offline=True`, `OptimizationError` from the local registry, and connected typed-session self-abort before backend guidance because the SDK does not execute/transmit the named selector (Traigent/Traigent#1752). Do not present them as usable options today; use `"auto"` for connected smart optimization and `"grid"`/`"random"` only for explicit local/offline search.
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
    return prompt_model(query, model=cfg["model"])
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
    return prompt_model(query, model=cfg["model"])
```

## Legacy mode selector (deprecated)

Earlier SDK versions accepted a string mode selector as an additional keyword argument
to `@traigent.optimize` or `ExecutionOptions`. That parameter is deprecated as of
SDK v0.14.2 — every value now emits a `DeprecationWarning` and remaps to the
`algorithm`/`offline` equivalents:

| Old string value | Behavior on current SDK | Modern equivalent |
|---|---|---|
| `"cloud"` | DeprecationWarning → cloud-first (semantic flip — no longer means local) | `algorithm="auto"` |
| `"privacy"` | DeprecationWarning → cloud-first, **no no-egress guarantee** | `algorithm="auto", offline=True` for no egress |
| `"hybrid"` / `"standard"` | DeprecationWarning → cloud-first | `algorithm="auto"` |
| `"local"` | DeprecationWarning → local-only | `offline=True` |

> **Key correction for `"cloud"` and `"privacy"`:** On the public `@traigent.optimize` path,
> passing these string values does **not** raise an error and does **not** activate a separate
> "full remote execution" mode — they remap to cloud-first with a warning. There is no
> `CloudRemoteExecutionUnavailableError` on the public decorator path; that error lives on a
> reserved cloud-client RPC surface unreachable from a decorated run.
>
> **No-egress is `offline=True`, not any string mode value.** The `"privacy"` value
> previously implied no-egress, but on current SDK it maps to cloud-first and may egress.
> Use `offline=True` explicitly for zero Traigent backend traffic.
>
> (Verified against `_warn_for_legacy_execution_options` in `traigent/api/decorators.py` (≈:650) and the mode-remap logic in `traigent/config/types.py:308-405`, SDK `origin/develop`.)

If you encounter these string values in legacy code, replace them with the `algorithm` and
`offline` equivalents from the table above.

## JavaScript / TypeScript Applications

To optimize an LLM application written in JavaScript/TypeScript, use the native
**`@traigent/sdk`** (see the `traigent-js` skill) rather than the Python SDK. The former
in-process JavaScript runtime `ExecutionOptions` fields are not part of the Python `ExecutionOptions`
— it is `extra="forbid"`, so passing them raises a pydantic `ValidationError` at construction.
