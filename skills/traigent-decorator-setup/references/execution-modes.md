# Execution Reference: `algorithm`, `offline`, and `ExecutionOptions`

Where and how an optimization run executes is controlled by two top-level knobs on
`@traigent.optimize(...)` — `algorithm` and `offline` — plus the advanced `ExecutionOptions`
bundle. There is **no `execution_mode` selector** anymore.

```python
import traigent
from traigent.api.decorators import ExecutionOptions
```

## The two execution knobs

| Knob | Type | Default | Description |
|---|---|---|---|
| `algorithm` | `str` | `"auto"` | `"auto"` uses the Traigent **cloud optimizer** (the backend proposes each next trial) while your trials run locally; on a connectivity failure it auto-degrades to a local search. `"grid"`/`"random"` run **entirely locally** (no backend round-trip). Smart optimizers (`"bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, `"optuna_random"`, `"optuna_grid"`, `"optuna_cmaes"`, `"optuna_nsga2"`, `"nsga2"`, `"cmaes"`, `"nsgaii"`, `"nsga_ii"`, `"cma_es"`) are **cloud-only** and raise if the cloud is unavailable. Unknown names are rejected. |
| `offline` | `bool` | `False` | `True` forces a fully local run with **zero backend egress** — no session, no tracking, no uploads. Equivalent env: `TRAIGENT_OFFLINE=1`. |

```python
@traigent.optimize(
    algorithm="auto",     # cloud-first; falls back to local if the backend is unreachable
    configuration_space={"model": ["gpt-3.5-turbo", "gpt-4"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return call_llm(model=cfg["model"], prompt=query)
```

## How each choice behaves

- **`algorithm="auto"` (default) — cloud-first.** The Traigent cloud proposes each configuration and learns across runs; **your agent and your LLM calls always run locally** (Traigent never runs your compute). If there is no API key or the backend is unreachable, the run **auto-degrades to a local `grid`/`random` search** with a one-line warning so it still completes (results sync on the next successful run). Smart algorithms requested explicitly do **not** silently downgrade — they raise.
- **`algorithm="grid"` / `"random"` — local.** The search runs entirely in the SDK with no backend round-trip. Non-sensitive telemetry still syncs if a key is present and `offline` is not set.
- **Smart algorithms — cloud-only.** Requesting one without a reachable cloud raises a clear error (`TRAIGENT_REQUIRE_CLOUD=1` also forces this — it disables the auto-fallback).
- **`offline=True` — no egress.** Nothing leaves your machine. Use this for air-gapped or strict-no-network runs.

> **Privacy, said honestly.** On the cloud path the SDK sends only **configuration IDs and numeric metrics** — never your dataset's example inputs, prompts, or outputs. "Privacy-preserving" is therefore the default. But it is **not** the same as "no network": for zero outbound traffic, use `offline=True`.

## Result provenance

Every result records where it actually ran in its metadata `source`:

| `source` | Meaning |
|---|---|
| `cloud_brain` | The cloud optimizer proposed the trials. |
| `local_fallback` | `auto` degraded to a local search because the backend was unreachable. |
| `explicit_local` | You chose `grid`/`random` (local by request). |
| `offline` | `offline=True` (or `TRAIGENT_OFFLINE`) — zero egress. |

## Optimizing an external service (HTTP / MCP)

To optimize an agent exposed behind an external HTTP/MCP endpoint, pass an **external-service
evaluator** (this replaces the old `execution_mode="hybrid_api"` + flat `hybrid_api_*` params).
The optimizer stays local; only each trial's *evaluation* is dispatched to your service.

```python
from traigent.api.decorators import ExternalServiceEvaluator, HybridAPIOptions

@traigent.optimize(
    evaluator=ExternalServiceEvaluator(
        hybrid_api=HybridAPIOptions(
            endpoint="https://my-agent.example.com/evaluate",
            transport_type="auto",      # "http" | "mcp" | "auto"
            batch_size=1,
            timeout=30.0,
            auth_header="Bearer ...",
        )
    ),
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

### Deprecated (do not use in new code)

These are **removed from the public surface** and accepted only as deprecated kwargs that emit a
`DeprecationWarning`:

| Removed | Use instead |
|---|---|
| `execution_mode="hybrid"` / `"standard"` | the default (`algorithm="auto"`) |
| `execution_mode="edge_analytics"` / `"local"` | `offline=True` |
| `execution_mode="hybrid_api"` + `hybrid_api_*` | `evaluator=ExternalServiceEvaluator(hybrid_api=HybridAPIOptions(...))` |
| `execution_mode="cloud"` | the default (`algorithm="auto"`) — note `cloud` historically ran *locally* |
| `privacy_enabled` | nothing — the cloud path is content-free by default; use `offline=True` for no egress |
| `cloud_fallback_policy` | nothing — auto-fallback is built in; `TRAIGENT_REQUIRE_CLOUD=1` disables it |

## Environment variables

| Variable | Effect |
|---|---|
| `TRAIGENT_OFFLINE=1` (or legacy `TRAIGENT_OFFLINE_MODE=1`) | Force fully-local, zero-egress execution. |
| `TRAIGENT_REQUIRE_CLOUD=1` | Disable the auto-fallback — a cloud-unavailable run errors instead of degrading to local. |
| `TRAIGENT_API_KEY` | Enables cloud optimization (`algorithm="auto"`) and portal tracking. Without it, `auto` degrades to a local search. |

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
**`@traigent/sdk`** (see the `traigent-js` skill) rather than the Python SDK. The former
in-process "JS bridge" `ExecutionOptions` fields are not part of the Python `ExecutionOptions`
— it is `extra="forbid"`, so passing them raises a pydantic `ValidationError` at construction.
