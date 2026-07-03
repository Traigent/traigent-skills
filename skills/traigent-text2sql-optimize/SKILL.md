---
name: traigent-text2sql-optimize
description: "End-to-end recipe to optimize a text2SQL agent with Traigent and reach high accuracy at low cost. Use when wiring a SPIDER-style NL->SQL agent with @traigent.optimize: execution-match scoring, model + structural knobs, weighted ACL objectives, mock dry-run, then a real portal-tracked run. Captures the working configuration that took a plain agent from 66.7% -> 90% on the cheap model."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.0.1"
---

# Traigent text2SQL optimization — the working recipe

## When to Use

Requires `traigent>=0.16.0`.

Use this when wiring a SPIDER-style text2SQL agent with objective execution-match
scoring and a Traigent optimization loop.

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
- `3 · 3 · 3 · 2 · 2 = 108` perms; `algorithm="random"` ~18 trials, plateau on. ~18 random
  trials over 108 perms is a **probe**, not coverage — it samples roughly a sixth of the space.
- **What it typically shows:** with nothing structural optimized, the picture is usually *"you
  get what you pay for"* — the model tier tends to dominate and the cheap model hasn't shone
  yet. Treat an 18-trial random read as suggestive; to actually *claim* tier dominance, add
  trials/seeds or run a `grid` pass over the reduced space.

**Run 2 — make the low-cost model SHINE (add the structural levers).**
- Keep the cheap model (+ maybe one mid), and **add the high-impact knobs that were held
  back:** `schema_context = {ddl_fk_rows, m_schema, compact}`, `fewshot_selector = similar`,
  `generation_path = {direct, plan_then_sql}`, keep `output_mode` unpinned.
- Keep the space at **~several hundred perms** and state the count; weight accuracy-first.
- **What it teaches:** in the original field run, the **low-cost model leapt up to match or
  beat the premium at a fraction of the cost.** *That jump — structural optimization on a
  cheap model — is the Traigent value.* Expect the direction, not the exact numbers: with
  random search, budget enough trials (or a grid pass on the pruned space) before reporting
  the jump on a new agent.
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
4. **Real run** (`algorithm="random"`, cost-capped, portal-tracked).
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
> See `traigent-run-plan/references/preflight.md`.

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

## 5. Run it (SDK v0.17-compatible API)
```python
import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions
# the selector is offline + algorithm
decorated = traigent.optimize(
    configuration_space=CONFIG_SPACE, objectives=OBJECTIVES, default_config=BASELINE,
    evaluation=EvaluationOptions(eval_dataset=DS, custom_evaluator=exec_eval),
    execution=ExecutionOptions(offline=False),   # False -> online/cloud; True -> local zero-egress
)(run_agent)
results = decorated.optimize_sync(max_trials=25, algorithm="random")  # or: await decorated.optimize(...)
```
- **Selector:** `ExecutionOptions(offline=...)` + the `algorithm` arg. Named smart algorithms (`bayesian`/`tpe`/`optuna`) are **not yet executable** — they fail before any trial runs with a clear error (`ConfigurationError` with `offline=True` or without cloud credentials; the backend also rejects them even when connected — verified against SDK 0.18.x). Use `"grid"`/`"random"`; `offline=True` keeps everything local (zero egress), `offline=False` syncs trials to the portal.
- **Mock first (free of LLM spend):** set `TRAIGENT_OFFLINE_MODE=true`, call `from traigent.testing import enable_mock_mode_for_quickstart; enable_mock_mode_for_quickstart()`, then run `offline=True`, `algorithm="grid"` (named smart algorithms are not yet executable). **Expect all-zero accuracy in mock**: this recipe scores by execution match, and every mock call returns the same canned text, so uniform 0.0 is the expected mock signature, not a broken pipeline (wiring, sampling, and scoring paths are what the mock validates). Mock also still consumes `optimization_samples` quota.
- **Real:** `TRAIGENT_RUN_COST_LIMIT` cap + `TRAIGENT_COST_APPROVED=true`, `offline=False`, `algorithm="random"` (or `"grid"`) — `bayesian`/`tpe`/`optuna` are roadmap names, not yet executable.
- **Dataset path:** `eval_dataset` must live under the CWD or `TRAIGENT_DATASET_ROOT` — set that env var if your data is elsewhere.

## Runnable example (copy-paste, self-contained)
`references/quickstart_text2sql.md` contains a **complete, runnable** recipe as a
fenced Python block — it builds its own tiny SQLite DB (no external data), so it
runs end-to-end in minutes and is the ice-breaker for the QuickStart:
```
python quickstart_text2sql.py --mock     # no LLM spend; validates wiring (all-zero accuracy expected)
python quickstart_text2sql.py --real      # cost-capped, portal-tracked
```
Swap the embedded DB + questions for the real SPIDER dev set to scale up — the wiring is identical.

## The proven winner (this slice)
`gpt-4o-mini · temp 0.2 · fewshot_k 2 · fewshot_selector=similar · generation_path=plan_then_sql · repair off`
-> **90.0%** @ ~$0.00009/query. The cheap model + similarity-selected few-shot +
plan-then-SQL beat both the mid model and (separately) a premium Sonnet config
(86.7% at 20-50x the cost).

## See also
- `traigent-run-plan/references/optimization-principles.md` — the key recommendations to apply on every run.
- `traigent-run-plan` — build the run-plan WITH the user before every run.
- `traigent-next-run` — after each run: the portal link, which knobs to keep/drop, and the next-run recommendation.
- `traigent-run-plan/references/preflight.md` — robust setup so runs go smoothly and track to the portal.

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

### Fetch the live profile (when available)
At session or skill start, if a configured Traigent client is available, seed the profile from the
backend with the skill name:

```python
policy = None
try: policy = await client.get_interaction_policy(skill="<this skill>")
except Exception: pass
```

Treat the returned `profile` as the STARTING seed: its control/expertise/pace axes plus
`question_budget`, `options_max`, and `jargon_level` replace the static defaults below. Explicit user
corrections in-conversation ALWAYS override the seed. If the call is unavailable or
`fallback_policy="static_v1"`, simply use the static defaults below; the SDK already fails soft.

- Always be concise.
- Match terminology to expertise. For `se`: plain engineering words; define each Traigent or
  statistics term once in plain language (no Bayesian / variance-decomposition / Pareto jargon
  unless asked). For `ds`: compact optimization and statistical terms are fine.
- Presenting options: show at most 3, mark exactly one **Recommended**, and give one short
  persona-appropriate trade-off per option.
- Autonomy. For `delegate` or `execute`: pick the recommended reversible action and proceed, asking
  only at hard gates. For `guided`: offer options with a recommendation at the key decisions. For
  `inspect` or `explore`: give brief rationale or evidence before asking, and ask before branch
  choices.
- Hard gates — always confirm regardless of persona: paid or provider model calls, sending data or
  private content off the machine, destructive edits, decisions the Traigent service is meant to
  return, and any missing fact the step truly requires.
- Always end by recommending the next Traigent skill or action to take.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
