# Optimization Principles

Use these principles before designing a Traigent optimization program or
run-plan. The first six are the core must-dos; the rest keep results trustworthy
and reproducible. They are field-tested from taking a text2SQL agent from 66.7%
to 90% accuracy at lower cost.

## Core recommendations

### P1 -- Span model tiers, including all tiers of at least one vendor

Expose **high + mid + low** capability tiers so the optimizer can route easy work
to cheap models and reserve a premium model for the hard cases. Include the
**full tier ladder of at least one vendor** (e.g. OpenAI `gpt-4o` / `gpt-4.1-mini`
/ `gpt-4o-mini`, or Anthropic `claude-sonnet` / `claude-haiku`) so you can
isolate the *capability* effect while holding vendor quirks constant -- then add
other vendors and open-source for breadth. Variety is the single biggest cost
lever.

### P2 -- Tune at least 3 significant AGENT knobs beyond model/temperature

Don't stop at model + sampling knobs. Add **>= 3 structural knobs** that change
*how the agent works* (for text2SQL: schema context, few-shot count + selector,
generation path / CoT, candidate voting, repair; for RAG: retriever, k, query
decomposition, context order, self-consistency). Structural knobs carry most of
the gains. See `skills/traigent-configuration-space/references/structural-spine.md`.

### P3 -- Record EVERY model knob, including implicit/default ones

Record all sampling/model knobs even when you didn't tune them -- `temperature`,
`top_p`, `max_tokens`, and **implicit ones like reasoning `effort`** (and the
model's default decoding). An untuned knob still has a value; capture it so runs
are reproducible and so a later run can promote it to a tuned knob.

### P4 -- Replace knobs that show no impact

After a run, rank each knob's impact on the objective. **Drop knobs with ~zero
impact** (especially if they add cost -- e.g. self-consistency that doesn't raise
accuracy) and **swap in better structural knobs**. This run-over-run swap is
where the ceiling moves (it took us 83.3% -> 90%). See `traigent-next-run`.

### P5 -- Vary the objective weights across runs

Run **multiple weight profiles**, don't fix one. Start **accuracy-first**
(e.g. ACL 0.80/0.15/0.05) to find the quality ceiling, then **raise the cost (and
latency) weight** as production usage/cost grows (e.g. 0.50/0.50/0.0) to find the
cheapest config at acceptable quality. The winner genuinely shifts with weights
(cheap model won under 80/15/05; the trade-offs change under 50/50). Add an
**effort** objective to penalize configs that do lots of work.

### P6 -- Record and name every run, including its permutation count

Every run gets a recorded **run-plan** capturing ALL its parameters -- dataset,
models, knobs+values, objectives+weights, algorithm, trial budget, cost cap,
execution selector (`algorithm` + `ExecutionOptions(offline=...)`), and the
**config-space permutation count** (product of value-counts across all tuned
knobs). Give it a **self-describing, unique name** encoding
who/weights/problem-space/**permutations**/date
(e.g. `Amir_ACL_80_15_05_txt2sql_216perms_20260620`). Record the permutation
count both in the name and as its own field, keep the filled plan with the run,
and add a **carry-forward** note of what won/lost to seed the next run. Seed the
carry-forward from data, not memory: before planning the next run, read the cohort
table for this agent+dataset (`analytics_list_experiment_group_configuration_runs`;
if your SDK build doesn't expose the experiment-group tools yet, use the prior
run's recorded results alone) and the prior run's ranked results, so what won/lost
is copied from recorded measures rather than recalled.

## Supporting principles

### P7 -- Hold a fixed, representative testbed; no leakage

Use the **same** representative eval set across compared runs (a fixed, seeded
sample), so differences reflect the config, not the data. Draw few-shot exemplars
from **outside** the testbed. Flag datasets under ~30-50 examples as
low-confidence.

### P8 -- Score objectively; meter cost and latency for real

Accuracy must be **objective** (execution match / exact match / programmatic),
not a subjective LLM judge. **Cost** = real tokens x provider price (route via a
metering proxy like OpenRouter/LiteLLM; supply custom pricing for models the SDK
doesn't price). **Latency** = real wall-clock. Mocked/zero KPIs invalidate the
run.

### P9 -- Verify every declared knob is actually injected

A knob declared in the config space but not read at the real call site is a
**silent no-op**. After wiring, confirm each tuned value reaches the LLM call.

### P10 -- Mock dry-run before spend; cap cost; start small

Always do a **free mock dry-run** to validate the pipeline, then a real run with a
**hard cost cap**. Start with a small trial budget / cheap models, then scale.

### P11 -- Label significance honestly

With < ~20 trials, call results **directional**, not significant. Per-knob
marginals average over the other knobs/models -- note sparse coverage. Don't
over-claim a winner from a small slice.

### P12 -- Confirm the run registered in the portal

After a run, verify the experiment appears in the portal **with its trials**. If
a run doesn't show up, it seems there may be a temporary connectivity issue -- we
recommend retrying the run and confirming the `View` link populates. See
`references/preflight.md`.

### P13 -- Decide from the Pareto frontier, not just the single winner

Pick the frontier point that fits your budget and latency SLA; the "best overall"
score is one choice among several efficient ones.
