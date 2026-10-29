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
so the cost objective is accurate. Measure latency as real wall-clock **milliseconds** —
bare `latency` is milliseconds on SDKs after 0.22.0
(see version-matrix: `latency-unit`).

When you use a `custom_evaluator`, emit `accuracy`, `cost`, and `latency` as real
per-eval metrics so the weighted objective uses real values. Also emit accuracy
under a distinct name (e.g. `exec_accuracy`) so the true accuracy is visible
alongside the composite score.

## Algorithm prerequisites

Named smart selectors execute on connected runs since 0.20.1
(see version-matrix: `smart-selector-exec`). On an authenticated connected run,
supported names (`algorithm="bayesian"`/`"tpe"`/`"optuna"`/`"optuna_tpe"`/
`"optuna_random"`) bind to the typed backend Optuna strategy; unsupported smart
names (`"nsga2"`/`"cmaes"`) fail fast with a capability message
(Traigent/Traigent#1752, #1758). They never run locally: `offline=True` raises
`ConfigurationError` and the local registry raises `OptimizationError`. Use
`algorithm="auto"` for default connected real runs; use `algorithm="grid"` or
`algorithm="random"` only for explicit local/offline search. A clean Python
3.11/3.12 environment is still recommended either way.

## Execution selector and portal tracking

**Current SDK contract:** the selector is `ExecutionOptions(offline=...)` + the
`algorithm` arg. Legacy selector names are gone. Default connected real runs to
**`offline=False`** (online) with `algorithm="auto"` (or omit `algorithm`): trials
run with portal tracking while the agent and data stay local (only configs +
numeric scores leave the machine). Named smart selectors (`bayesian`/`tpe`/`optuna`)
run only on authenticated connected runs (see "Algorithm prerequisites" above) and
never with `offline=True`. Use **`offline=True`** for a local run with zero Traigent backend
egress (grid/random only) ONLY when explicitly chosen; never switch silently. It stops Traigent
backend traffic only: your agent's model-provider calls still go out, and LiteLLM fetches its
pricing map at import unless `LITELLM_LOCAL_MODEL_COST_MAP=True` is set. After a run, **confirm the experiment
appears in the portal with its trials**. If it doesn't show up, it's likely a
temporary connectivity issue -- **retry the run** and confirm the printed `View`
link populates. Keep a hard cost cap (`TRAIGENT_RUN_COST_LIMIT`) on every real
run.

## Run naming

Set an explicit decorator `agent_name` (SDK 0.27.0+; `experiment_name` is its deprecated
alias, and `agent_name` wins if both are given) to pin a **stable agent identity**.
Name precedence is: explicit `agent_name` decorator argument; the deprecated
`experiment_name` argument; `TRAIGENT_EXPERIMENT_NAME`
checked at access time; deterministic self-describing default built at decoration
time as `"<func_name>[<obj1>,<obj2>,...][<knob1>,...]"` with at most 4 knobs
shown and a 120-character cap; bare `func.__name__` only when no objectives or
knobs were registered.

`agent_name` identifies the **agent**, not the run: the portal groups
optimization history by (agent, evaluation dataset). Use a short stable slug
naming the agent — e.g. `amir_txt2sql` — and reuse it for every run of that
agent.

**Do not** encode weights, permutation count, or a date into the name (e.g.
`Amir_ACL_80_15_05_txt2sql_216perms_20260620`). Each distinct value forks a new
agent, so a per-run name shatters the optimization history into one-run
fragments and makes runs *less* comparable, not more. The config-space size,
weights, and timestamp are already recorded on each run and are visible in the
history view.

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

1. Python 3.11/3.12 venv; `pip install "traigent>=0.21.3" "litellm>=1.106.0" scikit-learn scipy`
   (`litellm>=1.106.0` is the bundled pricing map that prices the OpenAI and Anthropic IDs these
   skills use; confirm any other provider's ID is priced before relying on a cost objective).
2. String-encode discrete knobs; `int()` at the call site.
3. Custom pricing for gateway models; emit real accuracy/cost/latency metrics.
4. `ExecutionOptions(offline=False)` (DEFAULT = online/cloud; `offline=True` local-only if chosen) + `algorithm` arg; cost cap set.
5. Mock dry-run (no provider spend; on SDK 0.31.0+ still priced against the cost cap, so use a small slice of a large dataset) -> confirm trials run (a reply-parsing scorer fails every trial under mock; stub the reply, do not catch the error) -> real run.
6. After the real run, confirm the experiment shows its trials; if not, retry.
7. Set an explicit `agent_name` (SDK 0.27.0+; `experiment_name` is the deprecated alias) — a
   stable agent slug, reused across runs. No permutation count, weights, or date in the name
   (that forks the agent); put what the run tests in `run_title=` / `run_description=`.
