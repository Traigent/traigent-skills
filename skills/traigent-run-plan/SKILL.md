---
name: traigent-run-plan
description: "MANDATORY pre-run protocol: before EVERY Traigent optimization run, render a fresh run plan and surface ALL SDK-configurable options to the user — get an explicit choice or an explicit 'accept default' for each. Never select any option silently (objectives, weights, models, knobs, algorithm, trials, budget, execution_mode, privacy, injection, plateau, reps, timeout, fallback, ...). Use before designing/launching any run; pairs with the filled-plan guardrail in run.py."
license: Apache-2.0
metadata:
  author: Amir
  version: "1.0"
---

# Traigent run plan — ASK ALL OPTIONS before every run (enforced)

The single most important rule: **a run never starts on parameters the user did
not see.** Before every run you MUST (1) copy `run-plan.template.md` to
`run-plan_<RUN_NAME>.md`, and (2) walk the user through **every** option below,
getting an explicit choice OR an explicit "accept the default" for each. Do not
pick any option on the user's behalf — defaults are *suggestions to confirm*, not
silent choices. `EXECUTION` defaults to **hybrid**; surface it like all the rest.

> Why this skill exists: a run was once launched having asked only a subset of
> options (and silently set `execution_mode`). That must never recur. The
> `run.py` guardrail enforces it mechanically — it ABORTS if any option key is
> missing or left as a `<FILL>` placeholder — and this skill enforces it in
> conversation.

## The protocol (do this every run)
0. **If prior runs exist, PRESENT the accumulated next-run conclusions first.**
   Derive from the results workbook (skill `traigent-knob-iteration` §5; reference
   `analyze_runs.py`) which **models** and **knobs** to keep/drop/add and the
   suggested **weight** shift, and show them to the user. Use these to PROPOSE the
   next plan's `MODELS` / `KNOB_*` / `ACL_WEIGHTS` / `CARRY_FORWARD` — the user
   still confirms every option (the analysis informs, it does not decide).
1. **Render** a fresh `run-plan_<RUN_NAME>.md` from the template (all options present).
2. **Ask the user about EVERY option group below.** Use `AskUserQuestion` in
   batches; for each option present the allowed values + the default and ask them
   to choose or confirm. Cover ALL groups — do not stop after the "big" ones.
3. **Write their answers** into the plan (no `<FILL>` left).
4. **Mock dry-run** (free) → then **real** only on explicit go.

## The COMPLETE option catalog (every SDK-configurable choice)
Ask about each. Allowed values / defaults shown.

**A. Identity** — `RUN_NAME` (who_ACL_weights_space_perms_date); `PROBLEM_SPACE`;
`AGENT`; `EXPERIMENT_NAME` (portal name).

**B. Objectives** — `OBJECTIVES` (accuracy/cost/latency/effort);
`ACL_WEIGHTS` (per objective, ~sum 1.0); `ORIENTATIONS` (accuracy=maximize, others=minimize).

**C. Dataset & scoring** — `DATASET` (fixed, seeded, no leakage); `SCORING`
(objective execution/exact-match via custom_evaluator, not an LLM judge);
`METRICS_EMITTED` (accuracy, cost, latency [+ a distinct exec_accuracy]).

**D. Models** — `MODELS`: span tiers + a full vendor ladder + open-source (P1).

**E. Knobs** — model knob + ≥3 structural knobs, each with its value list, all
injected & verified (P2/P9). Permutation count = product of all value-counts.

**F. Search** — `ALGORITHM` (bayesian/tpe/optuna = smart, need hybrid; grid/random
= local); `MAX_CONFIGS`; `TIMEOUT`; `PLATEAU_WINDOW` + `PLATEAU_EPSILON`
(convergence); `STRATEGY` / `STRATEGY_PARAMS` (advanced).

**G. Repetition & sampling** — `REPS_PER_TRIAL`; `REPS_AGGREGATION`
(mean/median/…); `MAX_TOTAL_EXAMPLES`; `SAMPLES_INCLUDE_PRUNED`; `PARALLELISM`.

**H. Cost** — `BUDGET_USD` (hard cap, P10); `COST_APPROVED`.

**I. Execution & privacy** — `EXECUTION` (**hybrid** default | local-only
edge_analytics | hybrid_api); `PRIVACY_ENABLED`; `CLOUD_FALLBACK_POLICY`
(auto/never); `LOCAL_STORAGE_PATH`; `SAVE_TO`; `MINIMAL_LOGGING`; `PROGRESS_BAR`.

**J. Config injection** — `INJECTION_MODE` (context/parameter); `CONFIG_PARAM`;
`AUTO_OVERRIDE_FRAMEWORKS`.

**K. Best-config reuse** — `DEFAULT_CONFIG`; `AUTO_LOAD_BEST`; `LOAD_FROM`;
`CONFIG_ID`; `BEST_CONFIG_SOURCE` (off/portal/local).

**L. Constraints** — `CONSTRAINTS`; `SAFETY_CONSTRAINTS`.

**M. Advanced** — `EFFECTUATION` (apply winner back); `PROMPT_REWRITE`;
`GROW_DATASET`; `SKILL_TRAIN`; `AGENTS` (multi-agent); `TVL`.

**N. Hybrid-API (Lane 2 only)** — `HYBRID_API_ENDPOINT`, `_BATCH_SIZE`,
`_PARALLELISM`, `_KEEP_ALIVE`.

**O. Mock dry-run** — `MOCK_BASE_ACCURACY`; `MOCK_VARIANCE`.

**Carry-forward** — what won/lost; weights for the next run.

## Rules
- Surface ALL of the above every run; never hide an option because it "usually
  defaults fine" — show the default and let the user confirm it.
- `EXECUTION = hybrid` is the default; any other mode must be a user choice.
- The plan is the record (P6); keep the filled file with the run.

## See also
- `traigent-optimization-principles` · `traigent-run-recommendations` · `traigent-text2sql-optimize`
