# In-run `safety_constraints`: a statistical run halt, not a trial filter

Requires `traigent>=0.28.0`. `safety_constraints` is accepted since 0.28.0
(see version-matrix: safety-constraints-impl).

On SDKs below 0.28.0, including 0.27.x, do not pass a non-empty
`safety_constraints` value: `@traigent.optimize(...)` raises
`NotImplementedError` at decoration time. Omit the argument or upgrade. Check
the installed `traigent.__version__` before pointing a user at this recipe.

## What it does

`safety_constraints=[hallucination_rate().below(0.1)]` (preset from
`traigent.api.safety`) on `@traigent.optimize` behaves as follows:

- **Soft, run-level.** A constraint is checked across the run's completed
  trials. It does not filter trials: a trial that breaks the bar is not
  failed or dropped, and an unsafe configuration can still be returned as
  `best_config`.
- **One sample = one completed trial.** The value compared to the bar is the
  trial-level metric (for example, the mean of the per-example
  `hallucination_rate` values over that trial's examples), not each example.
- **Evidence floor.** `min_samples` defaults to `30` and `confidence` to
  `0.95`. While fewer than `min_samples` trials have completed, the
  constraint never halts the run.
- **Halt rule.** At and after `min_samples` completed trials, the run stops
  with `OptimizationResult.stop_reason == "safety_constraint"` when the
  confidence lower bound on the share of compliant trials is below the
  required compliance rate: `1 - v` for `below(v)`, `v` for `above(v)`.
  The check runs after the `max_trials` check: on the trial that reaches
  `max_trials` (including `min_samples == max_trials`) a failing constraint
  leaves `stop_reason="max_trials_reached"`, and a run that ends below
  `min_samples` never checks it. A `stop_reason` other than
  `"safety_constraint"` is not a pass; the SDK reports no separate safety
  verdict. Keep `min_samples` below `max_trials`. Do not raise `max_trials`
  just to reach `min_samples`: every trial is a full evaluation pass.
  That formula assumes a metric on a [0, 1] scale: for `below(v)` with `v`
  outside [0, 1] (for example a `below(500)` latency bar) the SDK requires a
  compliance rate of `1.0`, and `above(v)` with `v > 1` requires `v`, which
  no finite-sample lower bound reaches, so even a fully compliant run halts
  at `min_samples`; constrain a 0..1 metric or ratio instead.
  This includes a run where every trial complied but there is not yet enough
  evidence: "not yet shown safe" halts the run the same way "shown unsafe"
  does.
- **Missing metric.** A trial that does not produce the constrained metric
  falls back to the metric's default. The `hallucination_rate()` preset
  defaults to `1.0`, so the trial counts as non-compliant. A custom
  `MetricKeyMetric` (from `traigent.api.safety`) defaults to `0.0`, so under
  `below(v)` a missing metric counts as compliant, exactly like a measured
  `0.0`. With a custom key, either always produce the metric or pass
  `default=1.0`.

### Sizing `min_samples` and `max_trials`

With the default `confidence=0.95`, `below(0.1)` requires a compliance rate
of `0.9`. Thirty out of thirty compliant trials do not clear that bound, so a
fully compliant run with the default `min_samples=30` halts at trial 30. With
`below(0.1, min_samples=35)` a fully compliant 40-trial run completes all 40
trials. A run with fewer completed trials than `min_samples` never halts at
all, so a constraint on a 10-trial run is inert unless you lower
`min_samples` — and a low `min_samples` halts even a fully compliant run.
Size `min_samples` and `max_trials` together.

## Runnable example

Each block writes a one-row dataset in the current directory and searches a
four-value grid offline in a four-trial run. The first two set
`min_samples=3` so the floor is reached inside the run.

A run whose trials all break the bar halts at the floor, and `best_config` is
still filled in from the unsafe trials:

```python runnable
import json

import traigent
from traigent.api.safety import hallucination_rate

with open("qa.jsonl", "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"input": {"q": "2+2"}, "output": "4"}) + "\n")


def accuracy(output, expected, config=None):
    return 1.0 if output == expected else 0.0


def hallucination(output, expected, config=None):
    return 0.5  # every trial is over the 0.1 bar


@traigent.optimize(
    configuration_space={"x": [0, 1, 2, 3]},
    objectives=["accuracy"],
    eval_dataset="qa.jsonl",
    metric_functions={"accuracy": accuracy, "hallucination_rate": hallucination},
    safety_constraints=[hallucination_rate().below(0.1, min_samples=3)],
    offline=True,
    algorithm="grid",
    max_trials=4,
)
def answer(q: str) -> str:
    traigent.get_config()
    return "4"


result = answer.optimize_sync()
assert result.stop_reason == "safety_constraint", result.stop_reason
assert len(result.trials) == 3  # halted at min_samples, one trial short of max_trials
assert result.best_config  # still populated: violating trials are not filtered
print(result.stop_reason, len(result.trials), result.best_config)
```

A run whose trials all comply halts at the same point, because three
compliant trials are not enough evidence for a `0.9` compliance rate:

```python runnable
import json

import traigent
from traigent.api.safety import hallucination_rate

with open("qa.jsonl", "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"input": {"q": "2+2"}, "output": "4"}) + "\n")


def accuracy(output, expected, config=None):
    return 1.0 if output == expected else 0.0


def hallucination(output, expected, config=None):
    return 0.0  # every trial complies


@traigent.optimize(
    configuration_space={"x": [0, 1, 2, 3]},
    objectives=["accuracy"],
    eval_dataset="qa.jsonl",
    metric_functions={"accuracy": accuracy, "hallucination_rate": hallucination},
    safety_constraints=[hallucination_rate().below(0.1, min_samples=3)],
    offline=True,
    algorithm="grid",
    max_trials=4,
)
def answer(q: str) -> str:
    traigent.get_config()
    return "4"


result = answer.optimize_sync()
assert result.stop_reason == "safety_constraint", result.stop_reason
assert len(result.trials) == 3  # halted although every trial complied
assert result.best_config  # still populated
print(result.stop_reason, len(result.trials), result.best_config)
```

A run with `min_samples == max_trials` whose trials all break the bar is
never stopped by the constraint: the `max_trials` check runs first on the
last trial, so the run ends `"max_trials_reached"` with an unsafe
`best_config`:

```python runnable
import json

import traigent
from traigent.api.safety import hallucination_rate

with open("qa.jsonl", "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"input": {"q": "2+2"}, "output": "4"}) + "\n")


def accuracy(output, expected, config=None):
    return 1.0 if output == expected else 0.0


def hallucination(output, expected, config=None):
    return 0.5  # every trial is over the 0.1 bar


@traigent.optimize(
    configuration_space={"x": [0, 1, 2, 3]},
    objectives=["accuracy"],
    eval_dataset="qa.jsonl",
    metric_functions={"accuracy": accuracy, "hallucination_rate": hallucination},
    safety_constraints=[hallucination_rate().below(0.1, min_samples=4)],
    offline=True,
    algorithm="grid",
    max_trials=4,
)
def answer(q: str) -> str:
    traigent.get_config()
    return "4"


result = answer.optimize_sync()
assert result.stop_reason == "max_trials_reached", result.stop_reason
assert len(result.trials) == 4  # every trial violated, yet no safety halt
assert result.best_config  # unsafe, and nothing on the result says so
print(result.stop_reason, len(result.trials), result.best_config)
```

## After the run

Read `result.stop_reason` before using `result.best_config`. A
`"safety_constraint"` stop means the run ended early. It does not mean the
returned configuration is safe. Any other `stop_reason` is not a pass either:
a failing constraint is not checked on the trial that reaches `max_trials`,
nor on a run that ends below `min_samples`, and the SDK reports no separate
safety verdict. `optimize()` / `optimize_sync()` applies
`best_config` to the decorated function as for any run, so after a safety
halt that instance already runs the winner, which may be unsafe. Run
optimization in a separate candidate process (the `traigent-analyze-results`
skill teaches the separate candidate process pattern), and promote only
through `PromotionGate` on a holdout (see `SKILL.md` → Promotion Gate).
