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
| `algorithm` | `str` | `"auto"` | `"auto"` uses the Traigent **cloud smart optimizer** while your trials run in your environment. `"grid"`/`"random"` run local search in the SDK. Named smart selectors execute on connected runs since 0.20.1 (see version-matrix: `smart-selector-exec`): `"bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, `"optuna_random"` bind to the typed backend Optuna strategy on authenticated connected runs, while unsupported smart names such as `"nsga2"`/`"cmaes"` fail fast with a capability message (Traigent/Traigent#1752, #1758). On every version, `offline=True` + any smart name raises `ConfigurationError` and the local registry supports only `grid`/`random` (`OptimizationError`). Unknown names are rejected. |
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
- **Named smart selectors — connected-only, executable since 0.20.1** (see version-matrix: `smart-selector-exec`). On authenticated connected runs, `"bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, and `"optuna_random"` bind to the typed backend Optuna strategy at session creation; unsupported smart names such as `"nsga2"`/`"cmaes"` fail fast with a capability message (Traigent/Traigent#1752, #1758; on 0.20.0 no named smart selector executed end-to-end). They never run locally: `offline=True` raises `ConfigurationError` at decoration time, and the local registry raises `OptimizationError`. Use `"auto"` when you want the SDK to pick the connected smart path, and `"grid"`/`"random"` only for explicit local/offline search.
- **`offline=True` — zero Traigent backend egress.** No session, no portal sync. For a run with no network
  traffic at all (air-gapped / strict-no-network), also set `LITELLM_LOCAL_MODEL_COST_MAP=True` before
  importing `litellm`, and use mock mode or a local model.

> **Data flow.** Portal-synced runs send configuration IDs and numeric metrics, not dataset example inputs, prompts, or outputs. For zero Traigent backend traffic, use `offline=True`; for zero outbound traffic at all, see the `offline=True` bullet above.

## Result sync

Results sync to the Traigent portal in every non-offline run, including local `grid` and
`random` search. `offline=True` disables backend egress and portal sync.

The portal's default Experiments list order reflects when each run's sync reached the
backend, not when it executed locally — a deferred or retried sync can list a run out of
your actual execution order. See `traigent-analyze-results` -> "Find Your Run on the Portal"
for how to identify a specific run instead of relying on list position.

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

## Legacy mode selector (deprecated, and two values now fail closed)

Earlier SDK versions accepted a string mode selector as an additional keyword argument
to `@traigent.optimize` or `ExecutionOptions`. That keyword argument is deprecated as of
SDK v0.14.2, but the values do **not** all behave the same way today:

| Old string value | Behavior on current SDK | Modern equivalent |
|---|---|---|
| `"cloud"` | **Raises `ConfigurationError` at decoration time** — fails closed, no warning-and-remap | `algorithm="auto"` |
| `"privacy"` | **Raises `ConfigurationError` at decoration time** — fails closed, no warning-and-remap | `algorithm="auto", offline=True` for no egress |
| `"hybrid"` / `"standard"` | `DeprecationWarning` → remaps to cloud-first | `algorithm="auto"` |
| `"local"` | remaps silently to local-only (`offline=True`), no warning | `offline=True` |

> **Key correction for `"cloud"` and `"privacy"`:** these two values do **not** warn-and-remap.
> The SDK now treats them as fail-closed legacy selectors (`traigent/config/types.py`), and
> passing either one as that legacy keyword argument on `@traigent.optimize(...)` **raises
> `ConfigurationError` at decoration time**, because compatibility normalization for them could
> otherwise route to cloud egress. There is no `CloudRemoteExecutionUnavailableError` on the
> public decorator path; that error lives on a reserved cloud-client RPC surface unreachable
> from a decorated run. Only `"hybrid"` and `"standard"` still warn-and-remap; `"local"` remaps silently.
>
> **No-egress is `offline=True`, not any string mode value.** The `"privacy"` value
> previously implied no-egress; on current SDK it no longer decorates at all — remove it and
> use `offline=True` explicitly for zero Traigent backend traffic.
>
> Repro: decorating with that legacy keyword argument set to `"cloud"` (objectives, a tiny
> configuration space, no other execution knobs) raises `ConfigurationError` at decoration
> time instead of decorating with a warning.
>
> (Verified against the SDK's fail-closed legacy-selector set in `traigent/config/types.py`, SDK 0.27.0.)

If you encounter `"hybrid"`/`"standard"`/`"local"` in legacy code, replace them with the
`algorithm`/`offline` equivalents above. If you encounter `"cloud"` or `"privacy"`, decoration
will already be failing — remove the argument and use the modern equivalent.

## JavaScript / TypeScript Applications

To optimize an LLM application written in JavaScript/TypeScript, use the native
**`@traigent/sdk`** (see the `traigent-js` skill) rather than the Python SDK. The former
in-process JavaScript runtime `ExecutionOptions` fields are not part of the Python `ExecutionOptions`
— it is `extra="forbid"`, so passing them raises a pydantic `ValidationError` at construction.
