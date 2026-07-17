<!-- Source of truth for the Traigent economics posture and the characterization survey. -->
<!-- Authored HERE, and only here. Byte-identical copies are GENERATED into each economics -->
<!-- skill's references/economics-characterization.v0.md by -->
<!-- tools/contract/sync_economics_reference.py, because a single-skill install copies only -->
<!-- skills/<name>/ and would otherwise leave every pointer dangling. Those copies are -->
<!-- generated artifacts: never edit one — edit this file and re-run the sync tool, then -->
<!-- python tools/contract/update_reference_hashes.py. -->
<!-- Skills POINT at their local copy (one line + a role sentence). Never restate the -->
<!-- posture or the question set inline in a SKILL.md — that is the duplication this file -->
<!-- exists to prevent. -->

# Traigent Optimization Economics & Characterization (v0)

This is the **one** canonical reference for: what posture a skill takes toward spending, the
five characterization questions, how the user's coding agent is expected to ask them, the
mandatory explanation duty, and where the answers are recorded until the closed submission
path ships.

Status: **v0 — a starting model, not a validated one.** Every dollar figure below is a
labeled starting assumption. None of them has been validated against outcome data. Do not
present any number here to a user as measured, benchmarked, or proven.

## 1. Posture (canonical — quote by reference, never copy)

> Optimization is a bounded investment, not a cost to avoid by default: when conservative
> expected value is positive, propose a small daily budget and run the cheapest test capable
> of producing a decision. Before spending, record the value channel, cap, frozen evaluator
> and baseline, required machine-verifiable receipt, and stop rule; narrative justification
> cannot raise the cap. Continue only when verified receipts support positive lower-bound
> value or positive value of further information; otherwise stop and show the no-spend case.

### What this changes, and what it does not

**Changed — cost avoidance is no longer the default.** The prior posture treated spending as
something to minimize first and justify second. In practice that produced agents that
proposed `$0` and never started, so the user never saw a result and never learned what a run
is worth. A bounded, capped, receipt-backed experiment is the default recommendation whenever
conservative expected value is positive.

**Not changed — every existing safety rule stands, unweakened:**

- Mock / dry-run validation before any real run.
- **Explicit user approval before any paid run.** Nothing in this document authorizes an
  agent to spend on a user's behalf without their explicit go-ahead. A positive expected
  value is an argument to *put to the user*, never a substitute for their approval.
- An explicit spend cap on every run.
- Machine-verifiable receipts, not narrative claims.
- A recorded stop rule, applied.
- Production safety: no fixture or mock path in production, no data leaving the machine
  without approval.

This reference governs **how much to invest**. It never governs **whether approval is
required** — it always is.

## 2. The five characterization questions

Ask only what cannot be confidently inferred. Every user confirms at least **Q1** and **Q3**;
never ask more than five. Each question is a **closed field**: the submitted value must be
one of the listed options, whatever wording the agent used to reach it.

Slot syntax for tailored wording: `{agent_name}`, `{dataset_name}`, `{observed_volume}`,
`{model_name}`, `{evidence}`. Fill every slot from real project context — an unfilled slot
is a bug, not a placeholder to show the user.

---

### Q1 — `value_channel` — always confirm explicitly

**Canonical question:** "What is the main result you want this agent to create?"

**Tailored template:** "What is the main result you want {agent_name} to create?"

| Option (exact) | Closed value |
|---|---|
| save developer/expert time | `developer_time_saved` |
| replace manual support/operations | `manual_ops_replaced` |
| process large volumes cheaper or faster | `volume_throughput` |
| increase revenue/customer success | `revenue_growth` |
| prevent costly mistakes | `mistake_prevention` |

Identifies: dominant value channel and initial archetype.

---

### Q2 — `daily_volume_band` — ask only when not confidently inferable

**Canonical question:** "How many completed tasks should it handle on a normal day?"

**Tailored template:** "How many completed tasks should {agent_name} handle on a normal day?
I see {observed_volume} — confirm?"

| Option (exact) | Closed value |
|---|---|
| under 100 | `band_lt_100` |
| 100–999 | `band_100_999` |
| 1,000–99,999 | `band_1k_99k` |
| 100,000–999,999 | `band_100k_999k` |
| 1 million or more | `band_1m_plus` |

Identifies: `N`, scale economics, and whether quality or unit cost dominates.

Inferable from trace timestamps and completed evaluations (high confidence for *observed*
volume). **Forecast volume is low-confidence — always confirm it before budgeting**, even
when observed volume is solid.

---

### Q3 — `error_cost_band` — always confirm explicitly

**Canonical question:** "What usually happens when one output is wrong?"

**Tailored template:** "What usually happens when {agent_name} gets one output wrong?"

| Option (exact) | Closed value |
|---|---|
| cheap retry under `$1` | `retry_lt_1` |
| human correction costing `$1–50` | `human_fix_1_50` |
| customer escalation/rework costing `$50–5,000` | `escalation_50_5k` |
| financial/security/regulated harm above `$5,000` | `severe_gt_5k` |
| not measured | `not_measured` |

Identifies: `L_bad`, error asymmetry, and required evidence strength.

Never infer this from code alone. Write-capable tools or a finance/PII/security domain raise
the *prior*, but dollar loss is always user-specific — Q3 is asked, not guessed.

---

### Q4 — `lifecycle_stage` — ask only when not confidently inferable

**Canonical question:** "Which best describes the agent today?"

**Tailored template:** "Which best describes {agent_name} today?"

| Option (exact) | Closed value |
|---|---|
| building without a trusted evaluation | `build_no_trusted_eval` |
| building with a trusted evaluation | `build_with_trusted_eval` |
| limited production and we pay model costs | `limited_prod_self_paid` |
| full production and we pay | `full_prod_self_paid` |
| production where a customer/business unit pays | `prod_customer_paid` |

Identifies: build/run phase, cost bearer, evidence maturity, and appropriate payback horizon.

Inferable (high confidence) from `offline` usage, optimization history, promotion/apply
calls, and production traces. Ask when no run history exists, or when the contractual payer
may differ from the API-key owner.

---

### Q5 — `human_cycle_hours_band` — ask only when not confidently inferable

**Canonical question:** "How much human work does one evaluation or tuning cycle require?"

**Tailored template:** "How much human work does one {dataset_name} evaluation or tuning
cycle take you today?"

| Option (exact) | Closed value |
|---|---|
| automated/under 1 hour | `lt_1h` |
| 1–8 hours | `1_8h` |
| 8–40 hours | `8_40h` |
| over 40 hours or specialist review | `gt_40h_or_specialist` |
| not measured | `not_measured` |

Identifies: developer, labeling, QA, and eval-issue-discovery value.

Git activity, labeling scripts, and review queues are weak proxies (low confidence) — prefer
asking when this channel carries the recommendation.

## 3. Who asks, and how

**The interviewer is the user's own coding agent — the agent reading this file, right now.**
Not a portal, not a Traigent web form. That has consequences:

1. **Name the real agent.** Use the actual function, service, or product name from the
   project — "your ticket classifier", not "your agent". Same for the dataset, the model, and
   the evaluator. `{agent_name}` is filled from the code, never left generic.
2. **Infer before asking.** Read the code, the traces, the dataset, the config. Q2, Q4, and
   Q5 are usually inferable; Q1 and Q3 are usually not.
3. **Present every inferred value as a confirmation carrying its evidence** — never as a
   silent default and never as a bare question. The evidence pointer is one concrete line
   naming what was read:

   > "I see ~3.1k runs/day in the traces over the last 14 days, so I've put {agent_name} in
   > the 1,000–99,999 band — confirm?"

   An inferred value with no evidence pointer is a **defaulted** value; record it as
   `defaulted`, not `inferred`, and lower its confidence accordingly.
4. **Confirm Q1 and Q3 explicitly, always.** These two set the value channel and the error
   cost — the entire recommendation pivots on them, and neither is reliably readable from
   code. A confident guess is not a confirmation; the user must actually answer.
5. **Ask Q2, Q4, and Q5 only when inference is not confident.** If the traces are clear,
   confirm and move on.
6. **Target two asked questions.** The minimum seamless flow is: infer Q2/Q4/Q5, confirm
   Q1 and Q3. More than four asked questions means inference was not attempted — go back and
   read the project.

## 4. The explanation duty — mandatory

**For every question and every confirmation, without exception, the agent must:**

1. **show the options**,
2. **recommend exactly one**, and
3. **explain WHY — in the user's own numbers.**

This is a **product requirement, not styling, and not optional**. It is the reason this flow
exists. Users do not yet know how much to invest in building, evaluating, and optimizing an
agent; teaching that — build, evaluate, and optimize each have a cost, a payback, and a
budget — is a core part of what Traigent is for. A recommendation delivered without its why
teaches nothing and has failed its purpose, even when the recommendation is correct.

"In the user's own numbers" means *their* agent, *their* volumes, *their* error costs — never
generic marketing arithmetic:

> **Recommended: customer escalation/rework costing `$50–5,000`.** Why: your
> `classify_ticket` runs ~3.1k times/day, and a misrouted ticket goes to a human queue rather
> than being retried automatically. At even `$50` per escalation, a 1-point accuracy gain is
> worth ~`$1.5k`/month — which is why a `$5`/day test is worth running rather than skipping.
> If wrong tickets are actually just retried for free, pick the first option instead and the
> budget drops accordingly.

Note the shape: options, one recommendation, the why in their numbers, **and** what would
change the answer.

### Reconciling with the interaction policy's three-option cap — the paging rule

The shared interaction policy caps **any single presentation** at three options with exactly
one marked **Recommended**. Every closed field here has **five** values, and all five stay
selectable. Both hold at once, by paging:

- **Page 1** — the value you recommend, marked **Recommended**, plus the one or two most
  plausible alternatives for *this* project. At most three options; exactly one Recommended.
  End the page by naming what is left and offering it: *"there are two other options if none
  of these fit — say the word and I'll show them."*
- **Page 2, and any page after it** — carry **the same overall recommendation** forward as
  one of the three options, still marked **Recommended**, plus up to two values not yet
  shown. Again at most three options, exactly one Recommended. The recommendation is the
  agent's standing answer for the whole field; it does not change just because the
  alternatives on screen changed. It changes only when the user tells you something new — and
  if it does change, say so explicitly rather than silently moving the label.
- **Repeat until every value has been shown, or the user picks.** Five values need at most
  two pages. Never render a page with more than three options, never render a page with zero
  or with two Recommended marks, and never drop a value because it did not fit on a page.

The user may pick **any** of the five values at any time, including one you have not shown
yet — if they name it, take it. The *submitted* value is always one of the five closed
values: presentation narrows, the contract does not.

Worked example for `error_cost_band` (five values), recommending `escalation_50_5k`:

| Page | Options shown | Recommended |
|---|---|---|
| 1 | `escalation_50_5k`, `human_fix_1_50`, `retry_lt_1` | `escalation_50_5k` |
| 2 (on request) | `escalation_50_5k` (carried), `severe_gt_5k`, `not_measured` | `escalation_50_5k` |

Two pages, three options each, one Recommended each, all five values reachable.

## 5. Templates are suggestions; the submission is the commitment

The wording above is a **template**, and the tailoring guidance is a **suggestion**. The agent
is encouraged to rewrite any question in the user's own vocabulary, merge two confirmations
into one sentence, reorder, or skip what it already knows.

**What is not negotiable is the submission.** The commitment is the completed record in the
closed schema (§6) — its fields, its closed values, its provenance, and its sharing policy.
Phrasing is free; the contract is fixed. An agent that invents a sixth field, submits a value
outside the enum, or records `inferred` with no evidence pointer has broken the contract no
matter how good the conversation was.

## 6. Recording the result (until the submission tool ships)

**There is no Traigent survey tool to call today.** Do not invent one, do not describe one to
the user, and do not claim the answers have been sent anywhere. A closed submission path is
planned; until it exists, the completed draft is written **locally only**.

Write the completed draft to **`.traigent/economics-survey.v0.json`** in the project root:

- **Local and uncommitted.** Add `.traigent/` to `.gitignore` if it is not already there.
- **Nothing is transmitted.** No part of this file leaves the machine in v0. Tell the user
  that plainly rather than implying a submission occurred.
- **Forward-compatible.** The shape below is the draft closed contract, so the file can be
  submitted as-is when the real path lands.

```json
{
  "schema": "traigent-economics-survey/v0",
  "agent_display_name": "your ticket classifier",
  "closed_fields": {
    "value_channel":          {"value": "mistake_prevention", "provenance": "asked",    "confidence": "high",   "evidence": null},
    "daily_volume_band":      {"value": "band_1k_99k",        "provenance": "inferred", "confidence": "high",   "evidence": "traces: ~3.1k runs/day over 14 days"},
    "error_cost_band":        {"value": "escalation_50_5k",   "provenance": "asked",    "confidence": "high",   "evidence": null},
    "lifecycle_stage":        {"value": "limited_prod_self_paid", "provenance": "inferred", "confidence": "medium", "evidence": "offline=False + OPENAI_API_KEY owned by this project"},
    "human_cycle_hours_band": {"value": "1_8h",               "provenance": "defaulted", "confidence": "low",   "evidence": null}
  },
  "typed_overrides": {
    "value_per_task_usd": null,
    "loss_per_bad_output_usd": null,
    "observed_daily_volume": 3100,
    "forecast_daily_volume": null,
    "human_minutes_per_example": null
  },
  "sharing_policy": {
    "share_closed_fields": true,
    "share_typed_overrides": false,
    "share_evidence_pointers": false
  }
}
```

Field rules:

- `provenance` is exactly one of `asked` | `inferred` | `defaulted`.
- `inferred` **requires** a non-null one-line `evidence` pointer. No pointer → record
  `defaulted`.
- `confidence` is `high` | `medium` | `low`.
- `agent_display_name` is presentation only.
- `sharing_policy` is the user's client-side allowlist over what may ever be sent. Default to
  the narrowest setting the user agrees to; bands may travel while raw evidence stays local.
  Never widen it without asking.

## 7. Turning answers into a bounded proposal (v0 starting assumptions)

**All figures below are starting assumptions [our-assumption-needs-validation]. Present them
as such.** Lead with the conservative lower bound, and always show the spend-`$0` case
alongside any recommendation.

**Recommended daily build budget**

```
B_day = clamp(floor, archetype_cap, 0.10 × LCB(RealizedV30) / 14)
```

where `RealizedV30 = P(start) × P(accept/deploy) × V30` — realized value, not headline value.

Initial floors / caps, by archetype:

| Archetype | Floor | Cap |
|---|---:|---:|
| Solo coding builder | `$5` | `$50` |
| Internal tool or research assistant | `$5` | `$100` |
| Support or extraction system | `$10` | `$250` |
| High-stakes agent or agent platform | `$25` | `$500` |

The floor is credit-backed until one real run produces evidence. Customer-paid spend requires
`LCB(RealizedV30) > 0` — a negative conservative bound means recommend `$0` and say so.

**Payback statement**

```
payback_days = total_optimization_cost / conservative_daily_realized_value
```

> "One avoided bad promotion worth `$C_wrong` pays for `C_wrong / (7 × B_day)` weeks of
> optimization."

**Stop / continue rule** — record it *before* spending, then apply it:

- **Continue** when `EVSI(next experiment) + LCB(incremental J$30) > next experiment cost`.
- **Stop** when `UCB(incremental J$30) ≤ next experiment cost`, or when attainable uptake
  makes realized value nonpositive.
- **Promote** only when `LCB(incremental J$30) > incremental serving cost + amortized
  integration cost` and payback is at most 30 days.

**Required receipt** — the claim envelope is recorded *before* spending (value channel,
frozen baseline, evaluator and dataset hashes, maximum spend, required receipt, stop rule),
and the spend is justified *after* only by a machine-verifiable receipt:

- **Winner receipt:** run ID, actual cost, paired delta and interval, selected configuration,
  promotion status, production follow-up.
- **Defect receipt:** example hash, defect category, independent confirmation, correction or
  test, reviewer time, duplicate check.
- **Savings receipt:** metered tokens, latency, calls, or dollars — never agent-authored
  estimates.

The proposing agent cannot validate its own receipt. Narrative quality never raises a cap or
unlocks budget; only verified receipts do. Unsupported claims unlock `$0`.

**Credibility rules.** Publish the formula and assumptions with the number. Show source,
confidence, and sensitivity for every inferred value. Never claim payback from a point
estimate when the conservative bound is negative. Recommendations stay independent of
Traigent's own pricing incentives — the honest answer is sometimes "don't spend".
