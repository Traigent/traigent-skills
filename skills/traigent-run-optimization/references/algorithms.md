# Algorithm Reference

Traigent uses `algorithm="auto"` by default and also supports explicit local and cloud smart algorithms. Pass the algorithm name as a string to `optimize()` or `optimize_sync()`.

```python
results = await func.optimize(max_trials=10)  # default algorithm="auto"
```

## Algorithm Comparison

| Algorithm | Strategy | Config Space Size | Trial Budget | Deterministic | Where search runs | Best For |
|---|---|---|---|---|---|---|
| `"auto"` | Traigent cloud smart default | Any | Any | No | **Cloud** | Most users, portal-tracked optimization |
| `"grid"` | Exhaustive enumeration | Small (< 50 combos) | Must cover full space | Yes | Local SDK search | Complete coverage, reproducibility |
| `"random"` | Uniform random sampling | Any | Limited (10-50) | No | Local SDK search | Large spaces, quick exploration |
| `"bayesian"` | Surrogate model guided | Medium-Large | 15-100 | No | **Cloud only** | Expensive trials, continuous params |
| `"optuna"` | Advanced TPE sampling | Large | 30+ | No | **Cloud only** | Advanced users, multi-objective |

> **`"bayesian"` and `"optuna"` (and the other smart optimizers) run in the Traigent cloud.** Use `"grid"` or `"random"` for local search. Results sync to the portal for every non-offline run, including local search; `offline=True` is the zero-egress path and does not sync results.

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
- Early exploration phase before switching to Bayesian
- Parameters have similar importance (no strong interactions)

### Behavior

- May sample the same configuration twice (with replacement)
- Stops when `max_trials` is reached
- Provides good coverage of high-dimensional spaces with fewer trials than grid

## Bayesian Optimization

Uses a probabilistic surrogate model to predict which configurations are likely to perform well, then focuses trials on the most promising regions. The planner runs in Traigent cloud; your decorated function and LLM calls run in your environment.

```python
results = await func.optimize(max_trials=30, algorithm="bayesian")
```

### When to Use

- Trials are expensive (each trial costs real money via LLM API calls)
- Configuration space has continuous parameters (temperature, top_p)
- You want to find good configs with fewer trials than random/grid
- Medium to large config spaces (50-10,000 combinations)

### Behavior

- First few trials are random (exploration phase)
- Subsequent trials are guided by the surrogate model (exploitation)
- Balances exploration vs exploitation automatically
- More sample-efficient than random search for smooth objective landscapes

### Limitations

- Requires several initial random trials before the model is useful (typically 5-10)
- Less effective for purely categorical spaces with no ordinal structure
- Non-deterministic: different runs may find different optima

## Optuna (Advanced)

Cloud-only access to advanced Optuna-style optimization, including pruning, multi-objective optimization, and custom samplers.

```python
results = await func.optimize(max_trials=50, algorithm="optuna")
```

### When to Use

- You need advanced Optuna features (pruning, custom samplers)
- Very large or complex search spaces
- Multi-objective optimization with Pareto frontier analysis
- You are already familiar with Optuna and want fine-grained control

### Behavior

- Uses TPE sampler by default
- Supports early stopping of unpromising trials (pruning)
- Can handle mixed categorical/continuous/integer parameter spaces

## Choosing an Algorithm

### Decision Guide

1. **No special constraint?** Omit `algorithm` and use the default `"auto"` cloud smart optimizer.
2. **Need deterministic local coverage?** Use `"grid"`.
3. **Need local search with a fixed budget?** Use `"random"`.
4. **Trials are expensive and you have cloud access?** Use `"bayesian"` for guided search.
5. **Need advanced cloud smart optimization?** Use `"optuna"`.

### Budget Guidelines

| Config Space Size | Recommended Algorithm | Suggested max_trials |
|---|---|---|
| Any size, normal setup | `"auto"` | Start with 10-30 |
| 1-10 and local coverage required | `"grid"` | Match space size |
| 10-50 and local coverage required | `"grid"` or `"random"` | Match space size or 20-30 |
| 50-500 and local search required | `"random"` | 20-50 |
| 50+ with cloud smart optimization | `"bayesian"` or `"optuna"` | 30-100 |

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

# Override at runtime; smart algorithms require Traigent cloud
results = await my_func.optimize(algorithm="bayesian", max_trials=20)
```
