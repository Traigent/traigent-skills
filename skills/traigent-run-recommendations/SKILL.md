---
name: traigent-run-recommendations
description: "Recommended setup so Traigent optimization runs go smoothly and results are accurate and portal-tracked. Use when wiring or launching a run. Covers robust knob encoding, objective cost/latency metering, algorithm prerequisites, the offline execution selector, run naming with permutation count, and light troubleshooting framed as recommended next steps."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.2"
---

# Traigent run recommendations — robust setup & smooth runs

## When to Use

Requires `traigent>=0.16.0`.

Use this when wiring or launching a Traigent optimization run.

Practical recommendations that make a run reliable, accurate, and portal-tracked.

## Knob encoding (most robust)
Encode discrete / integer knobs as **string categoricals** (e.g. `"0"/"2"/"4"`,
`"1"/"3"`) and `int()` them at the call site. Strings are discrete, JSON-native,
and unambiguous across optimizer backends — the most portable encoding for
fixed-set knobs. Reserve continuous ranges for genuinely continuous knobs.

## Make cost (and latency) objective
Route LLM calls through a metering proxy (OpenRouter / LiteLLM) so cost is real
tokens × price. If a model's price isn't auto-detected, supply it via
`TRAIGENT_CUSTOM_MODEL_PRICING_JSON` (or compute cost from token usage × price) so
the cost objective is accurate. Measure latency as real wall-clock.

## Emit the metrics your objectives use
When you use a `custom_evaluator`, emit `accuracy`, `cost`, and `latency` as real
per-eval metrics so the weighted objective uses real values. Also emit accuracy
under a distinct name (e.g. `exec_accuracy`) so the true accuracy is visible
alongside the composite score.

## Algorithm prerequisites
For `algorithm="bayesian"`, ensure `scikit-learn` and `scipy` are installed (or
use `tpe` / `optuna`). Use a clean Python 3.11/3.12 environment.

## Execution selector & portal tracking
**SDK v0.17 contract:** the selector is `ExecutionOptions(offline=...)` + the
`algorithm` arg. Legacy selector names are gone. Default to
**`offline=False`** (online): smart algorithms (`bayesian`/`tpe`/`optuna`) run in
the Traigent cloud with portal tracking while the agent and data stay local (only
configs + numeric scores leave the machine). Use **`offline=True`** for a local,
zero-egress run (grid/random only — no smart search) ONLY when explicitly chosen;
never switch silently. After a run, **confirm the experiment appears in the portal
with its trials**. If it doesn't show up, it's likely a temporary connectivity
issue — **retry the run** and confirm the printed `View` link populates. Keep a
hard cost cap (`TRAIGENT_RUN_COST_LIMIT`) on every real run.

The portal may show related runs as a cohort/group when they share the same agent
and canonical dataset. Use that grouping to browse related runs, not as a
merged result: configurations are not deduped across runs by tuned variables,
objectives, or config hashes. When acting on a configuration, copy the exact
source `experiment_id`, `experiment_run_id`, and `configuration_run_id`.

## Run naming (include the permutation count)
The portal experiment name comes from the decorated function's name — make it
self-descriptive: **who · weights · problem-space · permutation count · date**
(e.g. `Amir_ACL_80_15_05_txt2sql_216perms_20260620`). Recording the config-space
size (permutations) in the name makes runs comparable at a glance.

## Models & gateway
Fund your gateway before real runs. Prefer reliable low-cost **paid** models over
free-tier gateway models, which can be rate-limited under concurrency; if a model
returns no usable output it will show as low accuracy rather than an error, so
sanity-check each model with a small run first.

## Environment niceties
On Windows, set `PYTHONIOENCODING=utf-8` for clean CLI output. The SDK reads
`TRAIGENT_API_KEY` from the environment at run time — that's what authorizes the
run.

## Pre-flight checklist
1. Python 3.11/3.12 venv; `pip install traigent litellm scikit-learn scipy`.
2. String-encode discrete knobs; `int()` at the call site.
3. Custom pricing for gateway models; emit real accuracy/cost/latency metrics.
4. `ExecutionOptions(offline=False)` (DEFAULT = online/cloud; `offline=True` local-only if chosen) + `algorithm` arg; cost cap set.
5. Mock dry-run (free) → confirm trials run + metrics non-zero → real run.
6. After the real run, confirm the experiment shows its trials; if not, retry.
7. Name the run with its permutation count + weights + date.

## See also
- `traigent-run-plan` (MANDATORY: ask ALL run options before every run) · `traigent-optimization-principles` · `traigent-text2sql-optimize` · `traigent-next-run`
