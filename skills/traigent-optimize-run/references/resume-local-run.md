# Continue a Saved Local Run (`resume_from`)

Use this when the user wants to continue an interrupted or budget-limited **local** search without
paying again for trials that already finished. Requires an SDK that ships `resume_from` (check
`inspect.signature(fn.optimize_sync).parameters`); if it is absent, say so and do not improvise.

## Recipe

```python
from traigent.utils.persistence import PersistenceManager

manager = PersistenceManager(".traigent")           # where results are saved
saved_name = manager.save_result(first_results)      # persists the result with an integrity manifest

# Later (same dataset, scorer, agent and configuration space). Repeat the SAME local
# execution selector the first run used: the explicit local `algorithm` ("grid", "random", ...)
# if you passed one per call, or leave it out only if the function was declared offline/local.
results = my_function.optimize_sync(
    algorithm="grid",  # whatever the first run used; do not drop it
    max_trials=20,
    resume_from=saved_name,
)
```

A function declared with the default `auto` execution that was first run with a per-call local
`algorithm` resolves to connected execution when the resume call omits that argument, and resume
then raises the local-only `ValueError` below. Copy the first run's `algorithm` into the resume call.

`resume_from` also accepts an in-memory `OptimizationResult`. Keep `save_result` output as the
integrity-verified source of truth.

## Rules to relay to the user

- **Local runs only.** Cloud and hybrid runs raise `ValueError` ("resume_from supports local runs
  only for now").
  <!-- contract: literal "resume_from supports local runs only for now" in traigent.core.resume -->
- **Compatibility is checked.** Prior trials are reused only when the dataset, scorer, agent and
  configuration-space fingerprints all match the current run, and the trial completed. Unfinished
  trials are never reused or retried. If anything changed, expect a fresh search, not a reuse.
- **Accounting.** Reused trials count toward `max_trials` and the result. Their cost is reported but
  is not charged to this run's cost limit; only new trials spend. Any new spend still needs the
  user's approval as usual (see the cost gates in `SKILL.md`).
- **Integrity is verified.** A corrupted or tampered saved result raises `ValueError`. Report it and
  stop. Do not work around it: `allow_unverified_resume=True` trusts legacy results without a
  verifying manifest and is **unsafe**; use it only if the user explicitly accepts that risk.
  <!-- contract: raises ValueError in traigent.core.resume -->
