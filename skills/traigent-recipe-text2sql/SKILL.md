---
name: traigent-recipe-text2sql
description: "End-to-end recipe to optimize a text2SQL agent with Traigent and reach high accuracy at low cost. Use when wiring a SPIDER-style NL->SQL agent with @traigent.optimize: execution-match scoring, model + structural knobs, weighted ACL objectives, mock dry-run, then a real portal-tracked run. Captures the working configuration that took a plain agent from 20/30 -> 27/30 on its tuning slice on the cheap model (counts that predate the recipe's result_eq comparator and were not re-scored with it)."
license: Apache-2.0
metadata:
  traigent-audience: sdk-user
  traigent-topic: agent-optimization
  traigent-stage: recipe
  traigent-maturity: stable
  author: Traigent
  version: "1.0.19"
---

# Traigent text2SQL optimization — the working recipe

## When to Use

Requires `traigent>=0.24.0`; the runnable recipe below (`agent_name=`) needs `traigent>=0.27.0`.

Use this when wiring a SPIDER-style text2SQL agent with objective execution-match
scoring and a Traigent optimization loop.

A field-tested, end-to-end recipe that took a plain `gpt-4o-mini` NL->SQL agent
from **20 of 30 -> 27 of 30** execution-match on the 30-question SPIDER slice it was
tuned on, **while staying on the cheapest model** (~$0.00009/query). The gains came from
**prompt-structure knobs on a cheap model**, not from a premium model. Those are counts on
the tuning slice, not a held-out result — see "The winner on this slice" below. They also
predate the `result_eq` comparator taught below and were not re-scored with it, so they are
not directly comparable to a score you get from this recipe as written.

## What we observed on this benchmark (history, not a plan)
> **Scope: this is an observation about the text2SQL EXAMPLE, not a procedure to copy.** The
> models, knobs, space sizes and number of runs for any agent (this one included) come from the
> service plan: ask `traigent-analyze-guidance` (Mode A) and execute the choices it returns.

**Always state the permutation count** — when you present the plan, when you launch,
and when you report results. Repeat it every time; it's how the user sees the space
the optimizer is searching. Call a search whose trial budget is much smaller than the space a
**probe**, not coverage.

In the original field run we first searched a space that varied only minor settings, and the
picture was the usual *"you get what you pay for"*: model price tracked accuracy and the cheap
model had not shone. When the structural levers were added to the space (how the schema is
presented, how few-shot examples are chosen, whether the agent plans before writing SQL), the
**low-cost model rose to match or beat the premium one at a fraction of the cost.** *That
jump — structural optimization on a cheap model — is the Traigent value.* Treat it as a
direction, not a promise: on a new agent report it only after enough trials (or a grid pass on a
reduced space) to support it.

- Caveat: don't pair `plan_then_sql`/`cot` with `output_mode=sql_only` (they conflict —
  sql-only forbids the reasoning the plan path wants); keep output_mode unpinned so the
  optimizer pairs them correctly.

> **Injection:** you write `run_agent` ONCE; Traigent injects each trial's knob values
> (model, temperature, fewshot_k, …) and your agent reads them via
> `traigent.get_config()`. One function, hundreds of configs — no rewriting between trials.

## The loop (what actually works)
1. **Baseline** the un-optimized agent with an OBJECTIVE metric.
2. **Instrument** the entry function with `@traigent.optimize`.
3. **Mock dry-run** (no provider spend) to validate the pipeline.
4. **Real run** (`algorithm="auto"`, cost-capped, portal-tracked).
5. **Iterate** — drop knobs that didn't move accuracy, swap in better ones
   (see `traigent-analyze-guidance`), then re-run.

## 1. Objective scoring (non-negotiable for SQL)
Score by **execution match**, not string match: run the predicted SQL and the
gold SQL against the question's own SQLite DB and compare result sets. SPIDER is
multi-DB — each example carries a `db_id`; resolve schema + connection per `db_id`.

**Decide and document BOTH order policies — "order-insensitive" alone is ambiguous:**

- **Row order:** significant only when the gold query has `ORDER BY`; otherwise
  compare rows as a multiset (`collections.Counter`), never a plain `==` on lists.
- **Column order:** NOT significant. SPIDER gold projection order is arbitrary
  (gold `SELECT Population, Region` for *"What are the region and population…?"*);
  an agent answering in question order is semantically right. Both official Spider
  scorers forgive column order — the original `evaluation.py::eval_exec_match`
  matches columns by parsed column identity, and the official test-suite eval
  ([taoyds/test-suite-sql-eval](https://github.com/taoyds/test-suite-sql-eval);
  Zhong, Yu & Klein, EMNLP 2020) tries every column permutation. If your comparator
  is positional, arbitrary gold order silently caps accuracy for EVERY config — a
  constant offset optimization cannot remove (measured on a 30-example Spider-lite
  set: 2 examples failed on column order alone in 100% of 16 tested configurations,
  a de-facto 93% ceiling).
- **Column count still must match:** SPIDER gold sometimes projects extra columns
  (`SELECT CountryCode, max(Percentage)` when only codes were asked). The
  convention forgives column *order*, never missing/extra columns.

Before the first paid run, execute every gold once. A gold that fails to run is a dataset
error, not a bad candidate: it would score 0.0 for every candidate and separate nothing, so make
the scorer raise a distinct error naming the row (never score the candidate 0.0 for it, and do
not let it escape as a bare database exception) and exclude that id. Keep a gold that runs and
returns zero rows when that is the correct answer (for example "which invoices are overdue"
when none are): it still separates a correct query from one that wrongly returns rows. Return
`1.0` only when the prediction also executes and returns zero rows, `0.0` when it returns rows,
and `0.0` (never `None`, which fails the objective closed) when it fails to execute; record
the execution error separately from a legitimate empty result so the two are not conflated.

An empty gold has a limit: it also credits any wrong query that returns nothing. Do not fix
that by dropping the row. Keep it, count the empty-answer rows and report them separately, and
complement it: add fixture rows to the probe DB so the correct query returns data (for
example insert one overdue invoice and keep the original empty case on a second probe DB),
or score the question on both. In your reply, state this limitation and name the complement
you chose or recommend. Report accuracy with the excluded count. Run candidate SQL
only on a read-only handle with a watchdog and a size cap — never on the writable DB the agent
could mutate (the runnable reference below does both). Bound the watchdog by wall-clock time,
not by a VM-step count: a step cap also aborts correct SQL on a real-size table and scores it 0
like wrong SQL; report a timed-out query separately from an SQL error. Keep the read-only allowlist broad
enough for correct answers (window functions, JSON `->`/`->>`, math built-ins): a denied
feature scores a correct prediction 0 with no error. A real call LiteLLM cannot price has
an unknown cost, not a zero one: the reference refuses a `--real` run whose models have no
LiteLLM price, and exits nonzero if a call still cannot be priced. Failing only that row is not
enough, because the SDK averages a failed row's reported cost into the trial.

```python
from collections import Counter
from itertools import permutations

def result_eq(pred_rows, gold_rows, gold_has_order_by) -> bool:
    if len(pred_rows) != len(gold_rows):
        return False
    if not gold_rows:
        return True  # both empty: a legitimate empty answer (an execution error never reaches here)
    n = len(gold_rows[0])
    if len(pred_rows[0]) != n:
        return False
    for perm in permutations(range(n)):        # forgive arbitrary column order
        p = [tuple(r[i] for i in perm) for r in pred_rows]
        if (p == gold_rows) if gold_has_order_by else (Counter(p) == Counter(gold_rows)):
            return True
    return False

class GoldSQLError(ValueError):
    """The gold query itself failed: a dataset error, not a bad candidate."""

def exec_match(db_id, pred_sql, gold_sql, row_id) -> float:  # row_id is required: GoldSQLError names it
    g_ok, g = run(db_id, gold_sql)
    if not g_ok:
        raise GoldSQLError(f"gold SQL failed to run for row {row_id!r} (db {db_id}): fix or exclude it")
    p_ok, p = run(db_id, pred_sql)   # a candidate that fails to execute scores 0.0
    return 1.0 if (p_ok and result_eq(p, g, "order by" in gold_sql.lower())) else 0.0
```
SPIDER projections are 1–4 columns, so brute-force permutation is fine; for wide
results constrain the permutation space per-column as test-suite eval's
`get_constraint_permutation` does.

## 2. Multi-field inputs (db_id + gold)
Traigent maps only `input`/`output` dataset fields. Put the gold SQL under
`output` and carry `db_id` as an extra **top-level** field, which lands in
`example.metadata["db_id"]`. A row that wraps it in its own `metadata` object behaves
differently either side of 0.28.0 (Traigent/Traigent#1768): on `traigent>=0.28.0` the row's
`metadata` dict is **merged** into `example.metadata`, and on a key collision the nested value
wins over the top-level key; on 0.24.0-0.27.0 it nests under
`example.metadata["metadata"]["db_id"]`. Read both shapes if your code must run on both sides
of 0.28.0. Read everything in a **custom_evaluator** `(func, config, example) ->
ExampleResult` (it can call the agent with both `question` and `db_id`). See
`traigent-eval-build`.

`ExampleResult.example_id` must be unique per example: use the row's stable `id`
(see "Dataset prep: stable unique row ids" in `traigent-eval-build`). A constant
like the `db_id`, or a hash of identical rows, gives several rows one id and they
overwrite each other's cell in the local outcome matrix.

## 3. Configuration space — model + STRUCTURAL knobs

> **Starting from a vanilla single-call agent?** Each structural knob below
> (`fewshot_selector`, `generation_path`, `schema_context`, `repair`) must be
> *implemented* in your agent — and READ at the call site — before you declare
> it; declaring an unread knob is a silent no-op. `model` and `temperature` a
> plain single-call agent already has. If the rest are still vanilla, optimize
> the agent's REAL knobs first (model/temperature/prompt style) and add each
> structural knob to the space as you build the behavior for it — see
> `traigent-boost-agent`'s 12-Step Lifecycle Playbook, step 5 ("When the
> suggestions do not fit": drive the space from the client's real knobs).

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
> See `traigent-analyze-guidance/references/preflight.md`.
>
> **Correctness rule, not just a style tip:** `configuration_space` values and
> `default_config` must be JSON-TYPE-CONSISTENT per knob — the backend's config
> validation is fail-closed and type-strict, so int `0` is NOT the same as
> float `0.0`. A knob declared with float values but a default typed as an int
> (or vice versa) can be rejected outright; string-encoding discrete/int knobs
> (as above) sidesteps this entirely.

## 4. Weighted objectives (ACL)
```python
from traigent.core.objectives import ObjectiveSchema, ObjectiveDefinition
OBJECTIVES = ObjectiveSchema.from_objectives([
    ObjectiveDefinition(name="accuracy", weight=0.80, orientation="maximize"),
    ObjectiveDefinition(name="cost",     weight=0.15, orientation="minimize"),
    ObjectiveDefinition(name="latency",  weight=0.05, orientation="minimize"),
])
```
Accuracy-dominant (0.80) lets a much cheaper, nearly-as-accurate config win. When
using a custom_evaluator, emit `metrics={"accuracy":.., "cost":.., "latency":..}`
with REAL values so the weighted objective uses real cost/latency — `latency` in
**milliseconds** (the SDK's canonical unit for the bare metric) and `cost` as the
per-eval spend in USD.

## 5. Run it (SDK v0.17-compatible API)
```python
import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions
# the selector is offline + algorithm
decorated = traigent.optimize(
    configuration_space=CONFIG_SPACE, objectives=OBJECTIVES, default_config=BASELINE,
    evaluation=EvaluationOptions(eval_dataset=DS, custom_evaluator=exec_eval),
    execution=ExecutionOptions(offline=False),   # False -> online/cloud; True -> local, no Traigent backend egress (provider calls still go out)
)(run_agent)
result = decorated.optimize_sync(max_trials=25, algorithm="auto")  # or: await decorated.optimize(...)
```
- **Selector:** `ExecutionOptions(offline=...)` + the `algorithm` arg. With `offline=False`, omit `algorithm` or use `algorithm="auto"` for the default connected path to real cloud Optuna TPE. Use `"grid"`/`"random"` only for explicit local/offline search; `offline=True` keeps everything local (zero egress), `offline=False` syncs trials to the portal. Named smart selectors execute on connected runs since 0.20.1 (see version-matrix: `smart-selector-exec`): supported names (`bayesian`/`tpe`/`optuna`/`optuna_tpe`/`optuna_random`) bind to the typed backend Optuna strategy on authenticated connected runs; unsupported names (`nsga2`/`cmaes`) fail fast (Traigent/Traigent#1752, #1758). They never run locally: `offline=True` raises `ConfigurationError` and the local registry raises `OptimizationError`.
- **Mock first (no provider spend):** set `TRAIGENT_OFFLINE_MODE=true`, call `from traigent.testing import enable_mock_mode_for_quickstart; enable_mock_mode_for_quickstart()`, then run `offline=True`, `algorithm="grid"` (named smart algorithms never run offline — connected only). **Expect all-zero accuracy in mock**: this recipe scores by execution match, and every mock call returns the same canned text, so uniform 0.0 is the expected mock signature, not a broken pipeline (wiring, sampling, and scoring paths are what the mock validates). An offline mock touches no quota; a connected mock run (`offline=False` with a key) does. On SDK 0.31.0+ a mock run is still priced against the cost cap, so mock a few rows, not the full set (or use the SDK's documented mock exemption: `TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT=1` with an explicit non-production `ENVIRONMENT`, set on the mock process alone and never exported); never set `TRAIGENT_COST_APPROVED=true` for a mock run.
- **Real:** set `TRAIGENT_RUN_COST_LIMIT` to the user-approved cap (do not set `TRAIGENT_COST_APPROVED` up front; see `traigent-boost-agent` for the approval handshake), `offline=False`, omit `algorithm` or use `algorithm="auto"`; named smart selectors (`bayesian`/`tpe`/`optuna`) are selectable on authenticated connected runs on SDK 0.20.1+ (see the Selector bullet above).
- **`cloud_url` gate (don't skip this):** after a `--real`/`offline=False` run, check `result.cloud_url`. A missing `cloud_url` on a run you meant to be portal-tracked is easy to miss — trials still run and a `best_config` still comes back, so it reads as success (the SDK does log a fallback warning banner, but it's easy to scroll past). Verify the link before reporting the run as cloud-tracked. When it's missing, read `result.metadata["source"]` (`"local_fallback"` vs backend-tracked) for the provenance and `result.metadata.get("persistence_rejection_reason")` / `result.metadata.get("fallback_reason")` for the cause: a `persistence_rejection_reason` (e.g. a duplicate `example_id`) means the backend REJECTED the submission — fix the request, not the credentials; a `fallback_reason` with no rejection means check `TRAIGENT_API_KEY` and connectivity instead.
- **Dataset path:** `eval_dataset` must live under the CWD or `TRAIGENT_DATASET_ROOT` — set that env var if your data is elsewhere.

## Runnable example (copy-paste, self-contained)
`references/quickstart_text2sql.md` contains a **complete, runnable** recipe as a
fenced Python block — it builds its own tiny SQLite DB (no external data), so it
runs end-to-end in minutes and is the ice-breaker for the QuickStart:
```
python quickstart_text2sql.py --mock     # no LLM spend; validates wiring (all-zero accuracy expected)
python quickstart_text2sql.py --real      # cost-capped, portal-tracked
```
Swap the embedded DB + questions for the real SPIDER dev set to scale up — the wiring is identical;
raise the reference's per-query time budget (`_QUERY_BUDGET_S`) if its timeout warning fires on correct SQL.

## The winner on this slice (tuning score — not a held-out result)
`gpt-4o-mini · temp 0.2 · fewshot_k 2 · fewshot_selector=similar · generation_path=plan_then_sql · repair off`
scored **27 of 30** on the rows it was selected on, from a 20-of-30 baseline, at
~$0.00009/query; the cheap model + similarity-selected few-shot + plan-then-SQL beat
both the mid model and (separately) a premium Sonnet config (26 of 30 at 20-50x the
cost). That is a selection score on public Spider data: the winner was picked on these
rows, so the number is optimistic and carries no held-out check. These counts also predate
the `result_eq` comparator above and were not re-scored with it. Expect the direction on
your own agent, and score one recommended config on rows the search never saw before
quoting a lift.

## See also
- `traigent-analyze-guidance/references/optimization-principles.md` — the key recommendations to apply on every run.
- `traigent-analyze-guidance` — build the run-plan WITH the user before every run, and after each run: the portal link, which knobs to keep/drop, and the next-run recommendation.
- `traigent-analyze-guidance/references/preflight.md` — robust setup so runs go smoothly and track to the portal.

## Two scoring lessons from a real run
A real 2026-09-13 text2SQL run (8 trials, 18 questions) plateaued at 16/18 (88.9%)
for two checkable reasons — look for both before buying more trials:

1. **Extra columns fail on purpose.** The two items that failed in nearly every trial
   (0 of 8 and 1 of 8) returned correct rows with extra columns; the brief said "columns asked for, and
   no others," and this benchmark's execution-match contract is right to fail them.
   State whichever column contract *your* evaluator enforces, explicitly, in both the
   prompt and the grader — and when a run plateaus below 100%, check for this kind of
   output-contract failure before assuming the config just needs more trials.
2. **Errors are failures, not declines.** An agent that declines every question
   reached 4/18 (22%) for free, because some items are legitimately decline items —
   and provider errors / parse failures the agent wrapped in a decline string were
   miscounted as deliberate declines. Count execution failures and provider errors
   as failures, report answer-accuracy and decline-accuracy separately, and keep a
   decline-everything reference score in the readout so a decline-heavy config can't
   look good by accident.

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
import asyncio
policy = None
try:
    policy = asyncio.run(client.get_interaction_policy(skill="<this skill>"))
except Exception:
    pass
# Inside an async function (an event loop is already running), use
#   policy = await client.get_interaction_policy(skill="<this skill>")
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
- Recommend the next skill only after a result-bearing step (a run finishes, an analysis
  completes, a configuration validates) or an explicit decision point. Omit recommendations
  during setup or mid-walkthrough. Cap at 3 recommendations per response, each on its own line
  with a one-line eligibility reason (e.g., "traigent-analyze-results — ✓ run succeeded" or
  "traigent-optimize-run — ✓ config validated").
- When the user asks which Skills were used, answer briefly from what the session establishes: name the
  relevant Skills actually consulted, any that were unavailable, and any relevant deferred step with its
  reason. Keep installed availability, consultation and user-directed selection distinct, and never infer
  absence from non-use. Example: "Consulted quickstart and eval-build; post-run analysis is deferred
  because no optimization result exists." Do not volunteer this unasked.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
