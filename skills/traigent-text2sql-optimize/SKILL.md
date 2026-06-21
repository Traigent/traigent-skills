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

## The loop (what actually works)
1. **Baseline** the un-optimized agent with an OBJECTIVE metric.
2. **Instrument** the entry function with `@traigent.optimize`.
3. **Mock dry-run** (free) to validate the pipeline.
4. **Real run** (bayesian, cost-capped, portal-tracked).
5. **Iterate** — drop knobs that didn't move accuracy, swap in better ones
   (see `traigent-knob-iteration`), then re-run.

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

## 5. Run it
```python
@traigent.optimize(evaluation=EvaluationOptions(eval_dataset=DS, custom_evaluator=exec_eval),
                   execution=ExecutionOptions(execution_mode="hybrid", privacy_enabled=True),  # hybrid = DEFAULT
                   objectives=OBJECTIVES, configuration_space=CONFIG_SPACE, default_config=BASELINE)
def agent(question, db_id=None): ...
results = agent.optimize_sync(max_trials=25, algorithm="bayesian")  # mock first!
```
- **Mock first:** set `TRAIGENT_OFFLINE_MODE=true` + `enable_mock_mode_for_quickstart()` -> 0 cost.
- **Real:** `TRAIGENT_RUN_COST_LIMIT` cap, `TRAIGENT_COST_APPROVED=true`, `algorithm="bayesian"`.
- For bayesian, install `scikit-learn`+`scipy` (or use `tpe`/`optuna`).

## The proven winner (this slice)
`gpt-4o-mini · temp 0.2 · fewshot_k 2 · fewshot_selector=similar · generation_path=plan_then_sql · repair off`
-> **90.0%** @ ~$0.00009/query. The cheap model + similarity-selected few-shot +
plan-then-SQL beat both the mid model and (separately) a premium Sonnet config
(86.7% at 20-50x the cost).

## See also
- `traigent-optimization-principles` — the key recommendations to apply on every run.
- `traigent-knob-iteration` — measure which knobs mattered; swap in better ones.
- `traigent-results-consolidation` — collect all runs into one analysis workbook.
- `traigent-run-recommendations` — robust setup so runs go smoothly and track to the portal.
