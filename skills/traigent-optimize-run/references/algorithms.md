# Algorithm Reference

Traigent uses `algorithm="auto"` by default for connected real runs and also supports explicit local search algorithms (`"grid"`, `"random"`). Named smart selectors execute on connected runs since 0.20.1 (see version-matrix: `smart-selector-exec`); they never run locally or offline (see the note below the comparison table). Pass the algorithm name as a string to `optimize()` or `optimize_sync()`.

```python
results = await func.optimize(max_trials=10)  # default algorithm="auto"
```

## Algorithm Comparison

| Algorithm | Strategy | Config Space Size | Trial Budget | Deterministic | Where search runs | Best For |
|---|---|---|---|---|---|---|
| `"auto"` | Traigent cloud smart default | Any | Any | No | **Cloud** | Most users, portal-tracked optimization |
| `"grid"` | Exhaustive enumeration | Small (< 50 combos) | Must cover full space | Yes | Local SDK search | Complete coverage, reproducibility |
| `"random"` | Uniform random sampling | Any | Limited (10-50) | No | Local SDK search | Large spaces, quick exploration |
| `"bayesian"` | Surrogate model guided | Any | Any | No | **Cloud (connected only, SDK 0.20.1+)** | Named backend Optuna strategy |
| `"optuna"` | Advanced TPE sampling | Any | Any | No | **Cloud (connected only, SDK 0.20.1+)** | Named backend Optuna strategy |

> **Named smart selectors execute on connected runs since 0.20.1** (see version-matrix: `smart-selector-exec`). On an authenticated connected run, the supported names (`"bayesian"`, `"tpe"`, `"optuna"`, `"optuna_tpe"`, `"optuna_random"`) bind to the typed backend Optuna strategy and are serialized on session creation; unsupported smart names such as `"nsga2"`/`"cmaes"` fail fast before session creation with a capability message (Traigent/Traigent#1752, #1758; on 0.20.0 no named smart selector executed end-to-end). They never run locally on any version: with `offline=True` the decorator raises `ConfigurationError` at decoration time (*"requires managed optimization and cannot be used with offline=True"*), and the SDK's local optimizer registry rejects the names with `OptimizationError` (*"Smart optimization ('bayesian') runs in the Traigent cloud and is not available in the local SDK (which supports 'grid' and 'random')"*). Use `algorithm="auto"` (or omit `algorithm`) for the default connected smart path; use `"grid"` or `"random"` only for explicit local search. Results sync to the portal for every non-offline run, including local search; `offline=True` is the zero-egress path and does not sync results.

## Grid Search

Enumerates every combination in the configuration space, so the best in-space configuration on the evaluation dataset is always found.

```python
results = await func.optimize(algorithm="grid")
```

### Parameter Order

Control which parameters vary fastest vs slowest:

```python
results = await func.optimize(
    algorithm="grid",
    parameter_order={"model": 0, "temperature": 1, "max_tokens": 2},
)
```

Lower values vary slowest (outer loop), higher values vary fastest (inner loop). This is useful when you want to group trials by model to minimize cold-start costs.

### When to Use

- Configuration space has fewer than 50 total combinations
- You need deterministic, reproducible results
- You want to exhaustively evaluate every declared configuration (budget permitting) — the strongest in-space coverage, with no claim beyond the evaluation dataset
- Budget allows testing every combination

### Behavior

- Stops with `stop_reason="optimizer"` when all combinations are exhausted
- If `max_trials` is smaller than the config space, only a prefix is tested
- Iteration order is lexicographic by default (or controlled by `parameter_order`)

## Random Search

Samples configurations uniformly at random from the config space. Each trial is independent.

```python
results = await func.optimize(max_trials=20, algorithm="random")
```

### When to Use

- Large configuration spaces where exhaustive search is impractical
- You have a fixed trial budget and want broad coverage
- Early exploration phase before a larger `"random"`/`"grid"` budget (or a named smart selector on a connected run, SDK 0.20.1+)
- Parameters have similar importance (no strong interactions)

### Behavior

- May sample the same configuration twice (with replacement)
- Stops when `max_trials` is reached
- Provides good coverage of high-dimensional spaces with fewer trials than grid

## Bayesian Optimization — Connected Only (SDK 0.20.1+)

A probabilistic surrogate model predicts which configurations are likely to perform well and focuses trials on the most promising regions, with the planner running in the Traigent cloud while your decorated function and LLM calls run in your environment. Named smart selectors execute on connected runs since 0.20.1 (see version-matrix: `smart-selector-exec`): on an authenticated connected run, `algorithm="bayesian"` binds to the typed backend Optuna strategy at session creation (Traigent/Traigent#1752, #1758). It never runs locally — `ConfigurationError` with `offline=True`; `OptimizationError` from the local optimizer registry.

```python
# Connected only (TRAIGENT_API_KEY set, offline=False, SDK 0.20.1+):
results = await func.optimize(max_trials=30, algorithm="bayesian")

# Default connected smart path when you don't need a specific strategy:
results = await func.optimize(max_trials=30, algorithm="auto")
```

Use `"auto"` for connected real runs when you do not need a specific named strategy; use `"random"` only when you explicitly want local search.

## Optuna (Advanced) — Connected Only (SDK 0.20.1+)

Advanced Optuna-style optimization dispatched to the Traigent cloud. On an authenticated connected run (SDK 0.20.1+), `algorithm="optuna"`, `"optuna_tpe"`, and `"optuna_random"` bind to the typed backend Optuna strategy; unsupported smart names such as `"nsga2"`/`"cmaes"` fail fast before session creation with a capability message (see version-matrix: `smart-selector-exec`). Like all named smart selectors, they never run locally (`ConfigurationError` with `offline=True`; `OptimizationError` from the local optimizer registry). `algorithm="auto"` (the default) remains the connected Optuna TPE route when you don't pick a name.

```python
# Connected only (TRAIGENT_API_KEY set, offline=False, SDK 0.20.1+):
results = await func.optimize(max_trials=50, algorithm="optuna")
```

## Choosing an Algorithm

### Decision Guide

1. **No special constraint?** Omit `algorithm` and use the default `"auto"` cloud smart optimizer.
2. **Need deterministic local coverage?** Use `"grid"`.
3. **Need local search with a fixed budget, including large or expensive-trial spaces?** Use `"random"`. (`"bayesian"`/`"optuna"` are connected-only names — SDK 0.20.1+, see above.)

### Budget Guidelines

| Config Space Size | Recommended Algorithm | Suggested max_trials |
|---|---|---|
| Any size, normal setup | `"auto"` | Start with 10-30 |
| 1-10 and local coverage required | `"grid"` | Match space size |
| 10-50 and local coverage required | `"grid"` or `"random"` | Match space size or 20-30 |
| 50+ and local search required | `"random"` | 20-100 |

### Runtime Override

You can set the algorithm at decoration time and override it at runtime:

```python
import litellm

def prompt_model(prompt: str, *, model: str) -> str:
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

@traigent.optimize(
    algorithm="grid",  # Default algorithm
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(query, model=cfg["model"])

# Override at runtime — "auto"/"grid"/"random" work anywhere; named smart
# algorithms (e.g. "bayesian") are connected-only (SDK 0.20.1+, see above).
results = await my_func.optimize(algorithm="random", max_trials=20)
```
