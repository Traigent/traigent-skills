---
name: traigent-text2sql-optimize
description: "End-to-end recipe to optimize a text2SQL agent with Traigent and reach high accuracy at low cost. Use when wiring a SPIDER-style NL->SQL agent with @traigent.optimize: execution-match scoring, model + structural knobs, weighted ACL objectives, mock dry-run, then a real portal-tracked run. Captures the working configuration that took a plain agent from 66.7% -> 90% on the cheap model."
license: Apache-2.0
metadata:
  author: Amir
  version: "1.0"
---

# Traigent text2SQL optimization — the working recipe

A field-tested, end-to-end recipe that took a plain `gpt-4o-mini` NL->SQL agent
from **66.7% -> 90.0%** execution-match accuracy on a 30-question SPIDER slice
**while staying on the cheapest model** (~$0.00009/query). The gains came from
**prompt-structure knobs on a cheap model**, not from a premium model.

## The two-run lesson arc (the demo that lands)
> **Scope: this minimal-first teaching arc is for the text2SQL EXAMPLE only.** It starts
> small on purpose so the *lesson* lands. For a customer's **real agent** (usually a given),
> do the opposite — push for model variety (hi/med/low + ≥2 vendors) and SIGNIFICANT,
> low-latency knobs from run 1. See `traigent-run-plan` → "The EXAMPLE vs. the REAL agent."

**Always state the permutation count** — when you present the plan, when you launch,
and when you report results. Repeat it every time; it's how the user sees the space
the optimizer is searching.

**Run 1 — the raw model/cost picture (~100 perms, 3 model tiers, MINOR knobs only).**
- **Models: span 3 tiers** — high/premium (e.g. `gpt-4o`), mid (e.g. `claude-3-haiku`),
  low/cheap (e.g. `gpt-4o-mini`).
- **Vary only MINOR knobs:** temperature{0,0.2,0.4} · fewshot_k{0,2,4} · repair{off,on} ·
  output_mode{sql_only, allow_prose}. **Hold the high-impact STRUCTURAL levers at basic
  defaults** — `generation_path=direct`, `schema_context=ddl_fk`, `fewshot_selector=fixed`.
- `3 · 3 · 3 · 2 · 2 = 108` perms; bayesian ~18 trials, plateau on.
- **What it teaches:** with nothing structural optimized, the result is basically *"you
  get what you pay for"* — the model tier dominates and the cheap model hasn't shone yet.

**Run 2 — make the low-cost model SHINE (add the structural levers).**
- Keep the cheap model (+ maybe one mid), and **add the high-impact knobs that were held
  back:** `schema_context = {ddl_fk_rows, m_schema, compact}`, `fewshot_selector = similar`,
  `generation_path = {direct, plan_then_sql}`, keep `output_mode` unpinned.
- Keep the space at **~several hundred perms** and state the count; weight accuracy-first.
- **What it teaches:** the **low-cost model leaps up to match or beat the premium at a
  fraction of the cost.** *That jump — structural optimization on a cheap model — is the
  Traigent value.*
- Caveat: don't pair `plan_then_sql`/`cot` with `output_mode=sql_only` (they conflict —
  sql-only forbids the reasoning the plan path wants); keep output_mode unpinned so the
  optimizer pairs them correctly.

> **Injection:** you write `run_agent` ONCE; Traigent injects each trial's knob values
> (model, temperature, fewshot_k, …) and your agent reads them via
> `traigent.get_config()`. One function, hundreds of configs — no rewriting between trials.

## The loop (what actually works)
1. **Baseline** the un-optimized agent with an OBJECTIVE metric.
2. **Instrument** the entry function with `@traigent.optimize`.
3. **Mock dry-run** (free) to validate the pipeline.
4. **Real run** (bayesian, cost-capped, portal-tracked).
5. **Iterate** — drop knobs that didn't move accuracy, swap in better ones
   (see `traigent-next-run`), then re-run.

## 1. Objective scoring (non-negotiable for SQL)
Score by **execution match**, not string match: run the predicted SQL and the
gold SQL against the question's own SQLite DB and compare result sets
(order-insensitive). SPIDER is multi-DB — each example carries a `db_id`; resolve
schema + connection per `db_id`.

```python
def exec_match(db_id, pred_sql, gold_sql) -> float:
    p = run(db_id, pred_sql); g = run(db_id, gold_sql)
    return 1.0 if (p_ok and g_ok and p == g) else 0.0
```

## 2. Multi-field inputs (db_id + gold)
Traigent maps only `input`/`output` dataset fields. Put the gold SQL under
`output` and carry `db_id` as an extra field; read everything in a
**custom_evaluator** `(func, config, example) -> ExampleResult` (it can call the
agent with both `question` and `db_id`). See `traigent-build-evaluator`.

## 3. Configuration space — model + STRUCTURAL knobs
Don't stop at model+temperature. The high-value text2SQL knobs:

```python
CONFIG_SPACE = {
    "model": [low_cost, mid, open_source],         # span tiers via OpenRouter/LiteLLM
    "temperature": [0.0, 0.2, 0.4],
    "fewshot_k": ["0", "2", "4"],                  # in-domain exemplars (STRING-encoded)
    "fewshot_selector": ["fixed", "similar"],      # similar = pick exemplars closest to the question
    "generation_path": ["direct", "plan_then_sql"],# plan_then_sql = brief query plan/CoT then SQL
    "repair": ["off", "on"],                       # re-prompt once with the SQLite error
}
```
> Encode discrete/integer knobs as **strings** (`"0"/"2"/"4"`) and `int()` them at
> the call site — the most robust, portable encoding for fixed-set knobs.
> See `traigent-run-recommendations`.

## 4. Weighted objectives (ACL)
```python
from traigent.core.objectives import ObjectiveSchema, ObjectiveDefinition
OBJECTIVES = ObjectiveSchema(objectives=[
    ObjectiveDefinition(name="accuracy", weight=0.80, orientation="maximize"),
    ObjectiveDefinition(name="cost",     weight=0.15, orientation="minimize"),
    ObjectiveDefinition(name="latency",  weight=0.05, orientation="minimize"),
], weights_sum=1.0, weights_normalized={"accuracy":0.80,"cost":0.15,"latency":0.05})
```
Accuracy-dominant (0.80) lets a much cheaper, nearly-as-accurate config win. When
using a custom_evaluator, emit `metrics={"accuracy":.., "cost":.., "latency":..}`
with REAL values so the weighted objective uses real cost/latency.

## 5. Run it (SDK 0.16 API)
```python
import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions
# the selector is offline + algorithm — there is NO execution_mode/privacy_enabled in 0.16
decorated = traigent.optimize(
    configuration_space=CONFIG_SPACE, objectives=OBJECTIVES, default_config=BASELINE,
    evaluation=EvaluationOptions(eval_dataset=DS, custom_evaluator=exec_eval),
    execution=ExecutionOptions(offline=False),   # offline=False -> online/cloud (the "hybrid" default); True -> local zero-egress
)(run_agent)
results = decorated.optimize_sync(max_trials=25, algorithm="bayesian")  # or: await decorated.optimize(...)
```
- **0.16 selector:** `ExecutionOptions(offline=...)` + the `algorithm` arg — **no** `execution_mode`/`privacy_enabled` (removed). Smart algorithms (`bayesian`/`tpe`/`optuna`) run in the Traigent cloud when `offline=False` + authenticated; `offline=True` keeps everything local.
- **Mock first (free):** `os.environ["TRAIGENT_MOCK_LLM"]="true"` + `from traigent.testing import enable_mock_mode_for_quickstart; enable_mock_mode_for_quickstart()`, then run `offline=True`, `algorithm="grid"` (smart algorithms are cloud-only).
- **Real:** `TRAIGENT_RUN_COST_LIMIT` cap + `TRAIGENT_COST_APPROVED=true`, `offline=False`, `algorithm="bayesian"`. For bayesian install `scikit-learn`+`scipy` (or use `tpe`/`optuna`).
- **Dataset path:** 0.16 requires `eval_dataset` to live under the CWD or `TRAIGENT_DATASET_ROOT` — set that env var if your data is elsewhere.

## Runnable example (copy-paste, self-contained)
`references/quickstart_text2sql.py` is a **complete, runnable** version of everything
above — it builds its own tiny SQLite DB (no external data), so it runs end-to-end
in minutes and is the ice-breaker for the QuickStart:
```
python references/quickstart_text2sql.py --mock     # free; validates the pipeline
python references/quickstart_text2sql.py --real      # cost-capped, portal-tracked
```
Swap the embedded DB + questions for the real SPIDER dev set to scale up — the wiring is identical.

## The proven winner (this slice)
`gpt-4o-mini · temp 0.2 · fewshot_k 2 · fewshot_selector=similar · generation_path=plan_then_sql · repair off`
-> **90.0%** @ ~$0.00009/query. The cheap model + similarity-selected few-shot +
plan-then-SQL beat both the mid model and (separately) a premium Sonnet config
(86.7% at 20-50x the cost).

## See also
- `traigent-optimization-principles` — the key recommendations to apply on every run.
- `traigent-run-plan` — build the run-plan WITH the user before every run.
- `traigent-next-run` — after each run: the portal link, which knobs to keep/drop, and the next-run recommendation.
- `traigent-run-recommendations` — robust setup so runs go smoothly and track to the portal.
