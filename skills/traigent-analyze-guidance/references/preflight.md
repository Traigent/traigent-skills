# Run Preflight Checklist

Use this checklist before launching an approved Traigent optimization run. It
collects the reliability recommendations that make runs accurate, reproducible,
and visible in the portal.

## Knob encoding

Encode discrete / integer knobs as **string categoricals** (e.g. `"0"/"2"/"4"`,
`"1"/"3"`) and `int()` them at the call site. Strings are discrete, JSON-native,
and unambiguous across optimizer backends -- the most portable encoding for
fixed-set knobs. Reserve continuous ranges for genuinely continuous knobs.

## Cost and latency objectives

Route LLM calls through a metering proxy (OpenRouter / LiteLLM) so cost is real
tokens x price. If a model's price isn't auto-detected, supply it via
`TRAIGENT_CUSTOM_MODEL_PRICING_JSON` (or compute cost from token usage x price)
so the cost objective is accurate. Measure latency as real wall-clock **milliseconds**
(the SDK's canonical unit for the bare `latency` metric on SDKs after 0.22.0; earlier
local builtins recorded seconds).

When you use a `custom_evaluator`, emit `accuracy`, `cost`, and `latency` as real
per-eval metrics so the weighted objective uses real values. Also emit accuracy
under a distinct name (e.g. `exec_accuracy`) so the true accuracy is visible
alongside the composite score.

## Algorithm prerequisites

Named smart algorithms (`algorithm="bayesian"`/`"tpe"`/`"optuna"`/`"cmaes"`/`"nsga2"`)
are **not yet executable end-to-end** as named selectors (SDK 0.20.0). They
validate as known names but fail before any trial runs: `offline=True` raises
`ConfigurationError`, the local registry raises `OptimizationError`, and
connected typed runs self-abort before backend guidance because the SDK does
not execute/transmit the named selector (Traigent/Traigent#1752). Use
`algorithm="auto"` for connected real runs; use `algorithm="grid"` or
`algorithm="random"` only for explicit local/offline search. A clean Python
3.11/3.12 environment is still recommended either way.

## Execution selector and portal tracking

**Current SDK contract:** the selector is `ExecutionOptions(offline=...)` + the
`algorithm` arg. Legacy selector names are gone. Default connected real runs to
**`offline=False`** (online) with `algorithm="auto"` (or omit `algorithm`): trials
run with portal tracking while the agent and data stay local (only configs +
numeric scores leave the machine). Named smart algorithms (`bayesian`/`tpe`/`optuna`)
do **not** currently run as selector names -- do not select them expecting cloud
execution. Use **`offline=True`** for a local, zero-egress run (grid/random only)
ONLY when explicitly chosen; never switch silently. After a run, **confirm the experiment
appears in the portal with its trials**. If it doesn't show up, it's likely a
temporary connectivity issue -- **retry the run** and confirm the printed `View`
link populates. Keep a hard cost cap (`TRAIGENT_RUN_COST_LIMIT`) on every real
run.

## Run naming

Set an explicit decorator `experiment_name` when you need a stable portal label.
Name precedence is: explicit decorator argument; `TRAIGENT_EXPERIMENT_NAME`
checked at access time; deterministic self-describing default built at decoration
time as `"<func_name>[<obj1>,<obj2>,...][<knob1>,...]"` with at most 4 knobs
shown and a 120-character cap; bare `func.__name__` only when no objectives or
knobs were registered. Make explicit names self-descriptive: **who · weights ·
problem-space · permutation count · date** (e.g.
`Amir_ACL_80_15_05_txt2sql_216perms_20260620`). Recording the config-space size
(permutations) in the name makes runs comparable at a glance.

## Models and gateway

Fund your gateway before real runs. Prefer reliable low-cost **paid** models over
free-tier gateway models, which can be rate-limited under concurrency; if a model
returns no usable output it will show as low accuracy rather than an error, so
sanity-check each model with a small run first.

## Environment

On Windows, set `PYTHONIOENCODING=utf-8` for clean CLI output. The SDK reads
`TRAIGENT_API_KEY` from the environment at run time -- that's what authorizes the
run.

## Checklist

1. Python 3.11/3.12 venv; `pip install "traigent>=0.19" litellm scikit-learn scipy`.
2. String-encode discrete knobs; `int()` at the call site.
3. Custom pricing for gateway models; emit real accuracy/cost/latency metrics.
4. `ExecutionOptions(offline=False)` (DEFAULT = online/cloud; `offline=True` local-only if chosen) + `algorithm` arg; cost cap set.
5. Mock dry-run (free) -> confirm trials run + metrics non-zero -> real run.
6. After the real run, confirm the experiment shows its trials; if not, retry.
7. Set an explicit `experiment_name` with its permutation count + weights + date.
