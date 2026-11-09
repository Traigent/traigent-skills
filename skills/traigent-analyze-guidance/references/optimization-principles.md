# Optimization Principles

Use these principles before designing a Traigent optimization program or
run-plan. The first six are the core must-dos; the rest keep results trustworthy
and reproducible. They are field-tested from taking a text2SQL agent from 20/30
to 27/30 on its 30-row tuning slice at lower cost — a tuning-slice count chosen
by the search, so it is optimistic; the held-out number is the claim. These counts
(here) predate the text2SQL recipe's `result_eq` comparator and were not
re-scored with it.

## Core recommendations

### P1 -- Span capability tiers

Which models to try comes from the Traigent service plan (or an explicit user override), not from
this file. When you present or record the plan, check that it exposes more than one capability
tier so the optimizer can trade quality against cost, and ask the service for a refreshed plan if
it does not. Do not widen the plan locally.

### P2 -- Include structural knobs, not only model and sampling knobs

Knobs that change *how the agent works* (for text2SQL: schema context, few-shot selection,
generation path, repair; for RAG: retriever, query decomposition, context order) often matter
more than sampling knobs. Which ones to tune comes from the service plan; if the plan carries
only model and sampling knobs, say so and ask for a refreshed plan. See
`skills/traigent-optimize-config-space/references/structural-spine.md` for how to declare them.

### P3 -- Record EVERY model knob, including implicit/default ones

Record all sampling/model knobs even when you didn't tune them -- `temperature`,
`top_p`, `max_tokens`, and **implicit ones like reasoning `effort`** (and the
model's default decoding). An untuned knob still has a value; capture it so runs
are reproducible and so a later run can promote it to a tuned knob.

### P4 -- Replace knobs that show no impact

After a run with enough evidence, rank each knob's impact on the objective. **Drop a
knob only if the evidence supports it**: Mode C in `SKILL.md` and
`traigent-analyze-variable-importance` state when a ranking is trustworthy and when it is only
directional or not yet measured. Below that, a flat or empty ranking means "not yet measured":
keep the knob and treat the ranking as directional. A knob that is well measured and still does
not move the objective (especially if it adds cost -- e.g. self-consistency that doesn't raise
accuracy) is a candidate to drop. The service plan decides what to swap in; ask for a refreshed
plan rather than choosing replacements locally. See `traigent-analyze-guidance`.

### P5 -- Revisit the objective weights across runs

Weights encode a product decision, and the right ones can change as usage and cost grow. The
service plan proposes them; record the weights each run used, and when the user's priorities shift,
ask the service for a refreshed plan instead of re-weighting locally. The winner can shift with
the weights, so never compare scores across runs that used different ones.

### P6 -- Record and name every run, including its permutation count

Every run gets a recorded **run-plan** capturing ALL its parameters -- dataset,
models, knobs+values, objectives+weights, algorithm, trial budget, cost cap,
execution selector (`algorithm` + `ExecutionOptions(offline=...)`), and the
**config-space permutation count** (product of value-counts across all tuned
knobs). Give the **run-plan record** (its file name or title) a self-describing,
unique label encoding who/weights/problem-space/**permutations**/date, and record
the permutation count as its own field. Do not put that label in `agent_name` (SDK 0.27.0+;
`experiment_name` is its deprecated alias): `agent_name` stays the stable agent slug reused
across runs (see `references/preflight.md` -> "Run naming"). On SDK 0.27.0+ pass what this run
tests as `run_title=` / `run_description=` on the decorator. The SDK records each run's
timestamp automatically. Keep the filled plan with the run, and add a
**carry-forward** note of what won/lost to seed the next run. Seed the
carry-forward from data, not memory: before planning the next run, read the cohort
table for this agent+dataset (`analytics_list_experiment_group_configuration_runs`;
if your SDK build doesn't expose the experiment-group tools yet, use the prior
run's recorded results alone) and the prior run's ranked results, so what won/lost
is copied from recorded measures rather than recalled.

## Supporting principles

### P7 -- Hold a fixed, representative testbed; no leakage

Use the **same** representative eval set across compared runs (a fixed, seeded
sample), so differences reflect the config, not the data. Draw few-shot exemplars
from **outside** the testbed. Flag small datasets as low-confidence. Reserve a holdout slice **before** optimization begins and record
the partition (tuning/search slice, optional exemplar/few-shot bank, holdout
slice); if none exists, create one before treating any result as promotion-ready,
and preserve the same split across iteration rounds.

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

Always do a **no-spend mock dry-run** to validate the pipeline (on SDK 0.31.0+ the mock run
is still priced against the cost cap, so use a small slice of a large dataset), then a real run with a
**hard cost cap**. Start with a small trial budget / cheap models, then scale.

### P11 -- Label significance honestly

With few trials, call results **directional**, not significant. Per-knob
marginals average over the other knobs/models -- note sparse coverage. Don't
over-claim a winner from a small slice.

### P12 -- Confirm the run registered in the portal

After a run, verify the experiment appears in the portal **with its trials**. If
a run doesn't show up, keep the local result and recover the sync (see
`references/preflight.md`); repeating the paid search needs the user's approval.

The portal may group related runs that share the same agent and canonical
dataset, but that grouped view is only a browsing aid. Keep analytics and
promotion decisions tied to exact source run/configuration ids, not to the
group label.

### P13 -- Decide from the Pareto frontier, not just the single winner

Pick the frontier point that fits your budget and latency SLA; the "best overall"
score is one choice among several efficient ones. Search/optimization evidence is
not promotion evidence: promotion requires evaluating the chosen candidate against
the incumbent on the holdout slice, not on the search slice the winner was picked
from.
