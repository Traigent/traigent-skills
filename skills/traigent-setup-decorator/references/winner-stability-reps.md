# `winner_stability_reps`: opt-in post-selection winner rerun

Requires `traigent>=0.27.0`. **Unreleased today.** The currently shipping SDK is
`0.26.0` and does not accept `winner_stability_reps` anywhere — passing it to
`@traigent.optimize(...)` raises `TypeError: Unknown keyword arguments:
['winner_stability_reps']`, and passing it to `ExecutionOptions(...)` raises a
`pydantic.ValidationError` (`extra_forbidden`). Everything below documents an
interface that exists in source (`Traigent/Traigent` `develop`, commit
`867a7288`, landed 2026-08-11) but has not shipped in any tagged release —
`v0.26.0` (the latest tag) is an ancestor of that commit, not a descendant.
Check the installed `traigent.__version__` before pointing a user at this
path; do not present it as available today.

## What it does

`winner_stability_reps` is an opt-in, **measured-only** post-selection rerun
count for the winning configuration. Default `0` (off). Accepts an `int` from
`0` to `1000` inclusive; a value outside that range raises `ValueError`
(`"winner_stability_reps must be between 0 (off) and 1000"`), and a non-int
value raises `ValueError`/`pydantic.ValidationError` depending on which call
form carried it.

When `> 0`, after selection completes on a normally-completed run, the SDK
re-executes the winning config that many times on the same evaluation set
through the existing trial-execution path (no new engine) and attaches a
`winner_stability` block — `reps`, `mean`, `std`, `scores`, `config_hash`,
`evaluated_at` — to the result metadata.

**Measured evidence only** — read the numbers, do not treat them as a gate:

- The rerun runs strictly after selection and never changes which config won.
- It adds no gating and carries no stability guarantee.
- It must not feed contrast selection or any noise-floor calculation.
- A rerun failure logs and never fails the run; a partial measurement records
  only the measured subset.
- The count you choose is a **cost choice**, not an evidence-derived default —
  `3` is accepted only as a low-cost descriptive rerun; no replicate count on
  its own establishes stability.

**Not enterprise-gated.** This is distinct from the enterprise-gated
`reps_per_trial` (repeats every trial during search); `winner_stability_reps`
reruns only the already-selected winner and is not restricted to Traigent
Enterprise.

## How to set it

Two equivalent call forms, both **decorator-time only**:

```python runnable
import traigent

@traigent.optimize(
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
    offline=True,
    winner_stability_reps=3,  # direct decorator kwarg
)
def answer(query: str) -> str:
    cfg = traigent.get_config()
    return f"stub answer using {cfg['model']}"

assert answer.winner_stability_reps == 3
print("winner_stability_reps =", answer.winner_stability_reps)
```

Or nest it inside the `execution` bundle as a dict:

```python runnable
import traigent

@traigent.optimize(
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
    execution={"offline": True, "winner_stability_reps": 2},
)
def answer_bundled(query: str) -> str:
    cfg = traigent.get_config()
    return f"stub answer using {cfg['model']}"

assert answer_bundled.winner_stability_reps == 2
print("winner_stability_reps (bundled) =", answer_bundled.winner_stability_reps)
```

Or equivalently as `` `execution=ExecutionOptions(winner_stability_reps=2,
offline=True)` `` once the installed SDK's `ExecutionOptions` carries this
field — same effect as the dict form above.

## What is rejected

- **Both spellings at once, with conflicting values, raise `TypeError`.**
  `@traigent.optimize(winner_stability_reps=2,
  execution=ExecutionOptions(winner_stability_reps=3), ...)` fails with
  *"Conflicting values for 'winner_stability_reps' supplied via both direct
  arguments and grouped options. Remove one of the definitions."*
- **It is decorator-only — not a call-time argument.**
  `answer.optimize_sync(winner_stability_reps=3)` raises `TypeError`:
  *"winner_stability_reps is a @traigent.optimize decorator argument and is
  not accepted by .optimize() at call time; move it to the decorator:
  @traigent.optimize(winner_stability_reps=...). Previously this was silently
  ignored (issue #1683)."*

Both behaviors were verified directly against a local build of
`Traigent/Traigent` `origin/develop` (commit `867a7288` and later), not
inferred from prose.

(Source: `traigent/api/decorators.py` — `_coerce_winner_stability_reps`,
`ExecutionOptions.winner_stability_reps`, `_OPTIMIZE_DEFAULTS`,
`_DIRECT_OPTION_KEYS`; `traigent/core/optimized_function.py`;
`traigent/core/orchestrator.py`. Verified against `Traigent/Traigent`
`origin/develop`.)
