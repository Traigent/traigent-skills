# One approved cap across several paid phases (`ExecutionBudget`)

Requires `traigent>=0.26.0` (experimental). Below that floor `traigent.ExecutionBudget` does
not exist and `optimize()` has no `budget=` parameter — use per-run `cost_limit` and keep the
running total yourself.

Several paid phases under one approved total — a baseline, then the search, then holdout
scoring — share a cumulative cap by passing the same `ExecutionBudget` instance to every call:

```python
from traigent import ExecutionBudget

cap = ExecutionBudget(max_cost_usd=5.00)  # the figure the user approved, once
baseline = fn.optimize_sync(algorithm="grid", max_trials=12, budget=cap)  # your baseline size
search = fn.optimize_sync(algorithm="auto", max_trials=12, budget=cap)  # spends what is left
```

`ExecutionBudget(max_cost_usd=…, max_examples=…, deadline_seconds=…)` caps cost, examples, or
wall clock; whichever is hit first stops the run with `stop_reason="execution_budget"` and
`results.metadata["execution_budget"]` says which limit it was. Per-run `cost_limit` still
applies inside each call; the shared cap is the binding one.

It sees only SDK-tracked spend — calls your evaluator or a judge places directly are outside it
(Traigent/Traigent#2297). It holds its state in one Python object, so it cannot reach across
processes: phases that run in separate processes need a cap each.
