---
name: traigent-run-recommendations
description: "Recommended setup so Traigent optimization runs go smoothly and results are accurate and portal-tracked. Use when wiring or launching a run. Covers robust knob encoding, objective cost/latency metering, algorithm prerequisites, execution mode, run naming with permutation count, and light troubleshooting framed as recommended next steps."
license: Apache-2.0
metadata:
  author: Amir
  version: "1.1"
---

# Traigent run recommendations — robust setup & smooth runs

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

## Execution mode & portal tracking
**Default `execution_mode="hybrid"`** with `privacy_enabled=True`: trials run
locally with backend-supplied smart suggestions (the only mode that routes
bayesian/tpe/optuna) + portal tracking; agent and data stay local. Drop to
local-only `edge_analytics` (grid/random, no smart search) ONLY when explicitly
chosen — never switch the mode silently. After a run, **confirm the
experiment appears in the portal with its trials**. If a run does not show up, it
seems there may be a temporary connectivity issue — **we recommend retrying the
run** and confirming the printed `View` link populates. Keep a hard cost cap
(`TRAIGENT_RUN_COST_LIMIT`) on every real run.

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
4. `execution_mode="hybrid"` (DEFAULT; local-only `edge_analytics` only if chosen), `privacy_enabled=True`, cost cap set.
5. Mock dry-run (free) → confirm trials run + metrics non-zero → real run.
6. After the real run, confirm the experiment shows its trials; if not, retry.
7. Name the run with its permutation count + weights + date.

## See also
- `traigent-run-plan` (MANDATORY: ask ALL run options before every run) · `traigent-optimization-principles` · `traigent-text2sql-optimize` · `traigent-next-run` · `traigent-next-run`
