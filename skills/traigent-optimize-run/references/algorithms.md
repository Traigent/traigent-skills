# Algorithm Reference

Traigent uses `algorithm="auto"` by default for connected real runs and also supports explicit local search algorithms (`"grid"`, `"random"`). Named smart selectors (`"bayesian"`, `"optuna"`, `"tpe"`, `"cmaes"`, `"nsga2"`) validate as known names but are **not yet executable end-to-end** as named selectors (restamped against SDK 0.20.0; see the note below the comparison table). Pass the algorithm name as a string to `optimize()` or `optimize_sync()`.

```python
results = await func.optimize(max_trials=10)  # default algorithm="auto"
```

## Algorithm Comparison

| Algorithm | Strategy | Config Space Size | Trial Budget | Deterministic | Where search runs | Best For |
|---|---|---|---|---|---|---|
| `"auto"` | Traigent cloud smart default | Any | Any | No | **Cloud** | Most users, portal-tracked optimization |
| `"grid"` | Exhaustive enumeration | Small (< 50 combos) | Must cover full space | Yes | Local SDK search | Complete coverage, reproducibility |
| `"random"` | Uniform random sampling | Any | Limited (10-50) | No | Local SDK search | Large spaces, quick exploration |
| `"bayesian"` | Surrogate model guided | — | — | — | **Not executable today** | Roadmap only |
| `"optuna"` | Advanced TPE sampling | — | — | — | **Not executable today** | Roadmap only |

> **`"bayesian"`, `"optuna"`, and the other named smart selectors do not execute end-to-end today** (SDK 0.20.0). With `offline=True` the decorator raises `ConfigurationError` at decoration time (*"requires managed optimization and cannot be used with offline=True"*), and the SDK's local optimizer registry rejects the names with `OptimizationError` (*"Smart optimization ('bayesian') runs in the Traigent cloud and is not available in the local SDK (which supports 'grid' and 'random')"*). In connected typed-session runs, the SDK does not execute or transmit the named selector before it self-aborts ahead of backend guidance (Traigent/Traigent#1752); the backend would reject the name if it arrived. Use `algorithm="auto"` (or omit `algorithm`) for connected smart optimization; use `"grid"` or `"random"` only for explicit local search. Results sync to the portal for every non-offline run, including local search; `offline=True` is the zero-egress path and does not sync results.

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
- Early exploration phase before a larger `"random"`/`"grid"` budget (smart algorithms are roadmap, not an available next step today)
- Parameters have similar importance (no strong interactions)

### Behavior

- May sample the same configuration twice (with replacement)
- Stops when `max_trials` is reached
- Provides good coverage of high-dimensional spaces with fewer trials than grid

## Bayesian Optimization — Roadmap, Not Yet Executable

Intended design: a probabilistic surrogate model predicts which configurations are likely to perform well and focuses trials on the most promising regions, with the planner running in the Traigent cloud while your decorated function and LLM calls run in your environment. **The named `algorithm="bayesian"` selector is not available today.** It fails before any trial runs (`ConfigurationError` with `offline=True`; `OptimizationError` from the local optimizer registry). In connected typed-session runs the SDK self-aborts before backend guidance instead of executing or transmitting the selector (Traigent/Traigent#1752). For connected smart optimization, use `algorithm="auto"`.

```python
# Do NOT teach this as runnable — fails before any trial runs (clear SDK error):
# results = await func.optimize(max_trials=30, algorithm="bayesian")

# Use the connected smart path instead:
results = await func.optimize(max_trials=30, algorithm="auto")
```

Use `"auto"` for connected real runs over expensive, continuous-parameter spaces; use `"random"` only when you explicitly want local search. Revisit this section once the named smart selectors ship.

## Optuna (Advanced) — Roadmap, Not Yet Executable

Intended design: advanced Optuna-style optimization, including pruning, multi-objective optimization, and custom samplers, dispatched to the Traigent cloud. **The named `algorithm="optuna"` decorator/`optimize()` kwarg documented by this skill is not available today.** It fails before any trial runs (`ConfigurationError` with `offline=True`; `OptimizationError` from the local optimizer registry), and connected typed-session runs self-abort before backend guidance instead of executing or transmitting the selector (Traigent/Traigent#1752). The working connected Optuna TPE route is `algorithm="auto"` (the default), which maps to the backend's typed smart path.

```python
# Do NOT teach this as runnable — fails before any trial runs (clear SDK error):
# results = await func.optimize(max_trials=50, algorithm="optuna")
```

## Choosing an Algorithm

### Decision Guide

1. **No special constraint?** Omit `algorithm` and use the default `"auto"` cloud smart optimizer.
2. **Need deterministic local coverage?** Use `"grid"`.
3. **Need local search with a fixed budget, including large or expensive-trial spaces?** Use `"random"`. (`"bayesian"`/`"optuna"` are roadmap names — not yet executable, see above.)

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

# Override at runtime — stick to "auto"/"grid"/"random"; named smart
# algorithms (e.g. "bayesian") are roadmap and fail before any trial runs.
results = await my_func.optimize(algorithm="random", max_trials=20)
```
