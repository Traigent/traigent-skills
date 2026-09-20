# Convergence Analysis Patterns

## The convergence_info Dictionary

The `results.convergence_info` field is a dictionary of **summary** statistics about the
optimization run. It does **not** contain a per-trial score history — reconstruct the
improvement curve from `results.trials` (see below).

```python
results = func.optimize_sync()
info = results.convergence_info
```

### Fields

`convergence_info` carries these keys (parallel/pareto variants may add a few more):

| Field | Type | Description |
|---|---|---|
| `total_trials` | `int` | Total trials attempted. |
| `successful_trials` | `int` | Trials that completed without error. |
| `success_rate` | `float` | `successful_trials / total_trials`. |
| `algorithm` | `str` | Optimizer used (class name, e.g. `GridSearchOptimizer`). |

There is **no** `best_score_history` / `score_history` / `improvement_rate` /
`plateau_detected` / `exploration_ratio` key — guarding on those (`if "best_score_history"
in info`) silently no-ops. Build the curve yourself:

```python
def best_score_curve(results) -> list[float]:
    """Reconstruct the best-score-so-far curve from the trial list.

    Per-trial scores live in trial.metrics (key "score"); convergence_info only
    carries run-level summary stats, not the curve.
    """
    best, curve = None, []
    for trial in results.trials:               # trials are in run order
        score = trial.metrics.get("score")
        if score is None:                      # skip failed trials
            continue
        best = score if best is None else max(best, score)
        curve.append(best)
    return curve
```

## Interpreting Improvement Trends

### Healthy Convergence

A well-converging optimization shows rapid initial improvement that tapers off:

```python
history = best_score_curve(results)

# Check improvement in first half vs second half
midpoint = len(history) // 2
if midpoint > 0:
    first_half_gain = history[midpoint] - history[0]
    second_half_gain = history[-1] - history[midpoint]

    if second_half_gain < first_half_gain * 0.1:
        print("Optimization has converged - further trials unlikely to help")
    else:
        print("Still improving - consider running more trials")
```

### Stagnation

If the score is flat from the start, there may be a problem with the configuration space or evaluator:

```python
history = best_score_curve(results)
if len(history) > 3 and history[-1] == history[0]:
    print("No improvement at all - check:")
    print("  1. Is the configuration space meaningful?")
    print("  2. Does the evaluator differentiate between configs?")
    print("  3. Are all trials failing?")
    print(f"  Failed trials: {len(results.failed_trials)}/{len(results.trials)}")
```

### Late Improvement

If improvement comes late, the configuration space may be large and worth exploring further:

```python
history = best_score_curve(results)
if len(history) > 5:
    # Check if best score was found in last 20% of trials
    cutoff = int(len(history) * 0.8)
    late_best = max(history[cutoff:])
    early_best = max(history[:cutoff])
    if late_best > early_best:
        print("Best result found late - more trials may find even better configs")
```

## Plateau Detection

Traigent can stop optimization when it detects a plateau (no improvement over a window of
trials). The stop reason is `"plateau"` (`"convergence"` is the related early-stop reason).

```python
if results.stop_reason in ("plateau", "convergence"):
    print(f"Optimization stopped early (stop_reason={results.stop_reason})")

    # Reconstruct how many trials ran without improving the best score
    history = best_score_curve(results)
    stale = 0
    for score in reversed(history):
        if score < history[-1]:
            break
        stale += 1
    print(f"  ~{stale} trials at the final best score before stopping")

    # The result is likely near-optimal for this config space
    print(f"  Final best score: {results.best_score}")
```

## Evidence for the more-trials question

Summarise what the curve shows; whether to buy more trials is the decision brief's call
(`traigent-analyze-guidance`, Mode B) or, offline, a hypothesis to state — not a default:

```python
def trial_evidence(results) -> str:
    """Describe the stopping evidence; never a yes/no about spending."""

    if results.stop_reason in ("plateau", "convergence", "semantic_saturation"):
        return "converged for this space"
    if results.stop_reason == "optimizer":
        return "search space exhausted"
    if results.stop_reason in ("error", "vendor_error", "network_error"):
        return "stopped on an error - fix it before any rerun"
    if results.stop_reason in ("max_trials_reached", "cost_limit", "execution_budget"):
        history = best_score_curve(results)
        if len(history) >= 3 and history[-1] > history[-3]:
            return "cap reached while the best-so-far was still moving"
        return "cap reached with a flat best-so-far"
    return f"stopped: {results.stop_reason}"


results = func.optimize_sync()
print(f"Stop evidence: {trial_evidence(results)}")
```

## Comparing Convergence Across Runs

Use optimization history to compare convergence patterns:

```python
history = func.get_optimization_history()

for run in history:
    print(f"Run {run.optimization_id}:")
    print(f"  Algorithm: {run.algorithm}")
    print(f"  Trials: {len(run.trials)}")
    print(f"  Best score: {run.best_score}")
    print(f"  Stop reason: {run.stop_reason}")
    print(f"  Duration: {run.duration:.1f}s")

    curve = best_score_curve(run)
    if curve:
        print(f"  Score range: {curve[0]:.3f} -> {curve[-1]:.3f}")
    print()
```

## Convergence Visualization

If you want to plot convergence (requires matplotlib):

```python
import matplotlib.pyplot as plt

curve = best_score_curve(results)
per_trial = [t.metrics.get("score") for t in results.trials if t.metrics.get("score") is not None]

plt.figure(figsize=(10, 5))
plt.plot(curve, label="Best score so far")
plt.scatter(range(len(per_trial)), per_trial, alpha=0.3, label="Individual trials")
plt.xlabel("Trial")
plt.ylabel("Score")
plt.title(f"Convergence (stop_reason={results.stop_reason})")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("convergence.png")
```
