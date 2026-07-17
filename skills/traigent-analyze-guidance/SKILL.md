---
name: traigent-analyze-guidance
description: "What should this Traigent optimization run be, and what next? Three modes: (A) pre-run — fetch the service run-plan, present objectives/models/knobs/search/budget/offline options, apply preflight; (B) post-run, portal-tracked — fetch `traigent guidance next RUN_ID --json`, validate the Planner V2 treatment, lifecycle, certificate label, and authoritative decision, then execute only its opaque decision id; (C) offline/local fallback — diagnose flat/noisy/negative local results, which knob mattered, example evidence, form the next iteration hypothesis when offline=True or no service payload. Portal-tracked decisions come from Traigent, never local markdown."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.1.1"
---

# Traigent Analyze Guidance

## When to Use

Requires `traigent>=0.21.3` with `traigent guidance` for Planner V2. Existing
lifecycles pinned to v1 may continue using `traigent next-steps`; never mix v1
and v2 decisions inside one experiment arm.

Use this skill whenever you need to answer "what should this optimization run
be, and what should I do after it?" It has three strict modes and one doctrine:
**for portal-tracked runs the decision comes from the Traigent service, never
from local markdown reasoning.**

- **Mode A — pre-run plan:** fetch the service run-plan, confirm options, mock
  dry-run, launch on explicit go.
- **Mode B — post-run, portal-tracked:** fetch and follow the server-owned
  next-step payload, then loop back to Mode A.
- **Mode C — offline/local fallback:** diagnose local results and form ONE next
  hypothesis when no service payload is available.

## Optimization Economics — Read This Before Sizing a Run

**Do not default to recommending zero spend.** The canonical Traigent posture on spending,
the five characterization questions with their exact options, the tailoring rules, the
explanation duty, and the local survey draft contract all live in one place:
**`docs/shared/economics-characterization.v0.md`**. Read it before you propose, size, or
decline a run — it is the source of truth and is deliberately not restated here.

**This skill's part:** weigh the next run's cost against conservative value and the value of
the further information it would buy. This shapes *how much* to propose; it never overrides
the Traigent service, which still owns the next-step decision itself.

**Mandatory whenever you relay any of it:** show the options, recommend exactly one, and
explain **why in the user's own numbers** — their agent, their volumes, their error costs. The
explanation is a product requirement, not decoration.

Safety is unchanged and unweakened: mock/dry-run first, **explicit user approval before any
paid run**, an explicit spend cap, and the recorded stop rule. The economics reference sets
*how much* to invest; it never affects *whether* approval is required — it always is.

## Mode Arbitration

| Situation | Mode |
|---|---|
| About to design or launch a run (any run, always) | **A** — fetch and confirm the service run-plan |
| A portal-tracked run just completed | **B** — fetch `traigent guidance next RUN_ID --json` first |
| `offline=True`, no backend access, the service payload is unavailable, or the service flagged local evidence for diagnosis | **C** — local diagnosis, one hypothesis |

Portal-tracked runs go through Mode B first. Pre-run is always Mode A. Mode C
applies only when the Mode A/B service payloads are unavailable or for local
evidence diagnosis.

---

## Mode A — Pre-Run Plan

Use this before designing or launching any Traigent optimization run.

This mode is a thin client. It gathers the minimum run context, asks the
Traigent service for an allowlisted plan, presents that payload to the user, and
executes only the returned steps after the user approves. Do not invent or
improve the plan locally.

### Boundary

The recommended plan comes from the Traigent service via `traigent plan` or the
MCP tool `get_optimization_plan`. The returned payload is advisory and currently
static guidance: expect `phase` such as `P1_STATIC`, plus `evidence_level`,
`caveat`, and `advisory`.

This requires an SDK build that ships the optimization-plan tool (the `traigent
plan` CLI / `get_optimization_plan` MCP tool). If your installed SDK does not
expose it yet, tell the user the plan service is not available in this build and
fall back to `traigent recommend` for knob recommendations (see
`traigent-optimize-config-space`) — never fabricate a plan locally.

Do not embed local planning intelligence in this skill:

- Do not choose or rank models, knobs, algorithms, budgets, or option order in markdown.
- Do not compute plan-quality bands, search-space rules, or recommended trial counts locally.
- Do not add a replacement plan if the service omits one. Ask the service again with clearer context or stop for user input.
- Do not treat the advisory plan as proof that a real run will improve. The mock and heldout results remain the evidence.

### Protocol

1. Gather a short summary from the user or project files:
   - task description and agent entrypoint,
   - dataset size and holdout split — confirm a holdout slice is reserved and disjoint from the tuning slice; if none exists, the plan must say so and create one before optimization begins,
   - objectives the user cares about,
   - budget or maximum spend for the run.
2. Fetch the plan from the Traigent service:
   - Prefer `traigent plan` when the CLI is available.
   - Use `get_optimization_plan` when working through the Traigent MCP surface.
   - Pass only the short summary and any existing run id or portal context the user approved.
3. Validate the response shape before presenting it. The allowlisted top-level
   keys are `schema_version`, `phase`, `plan`, `steps`, `evidence_level`,
   `caveat`, and `advisory`. The `plan` object may include `objectives`,
   `models`, `knobs`, `algorithm`, `max_trials`, `cost_limit_usd`, and `offline`.
4. Present the returned plan option by option. For each option, show:
   - the exact value or choices returned by the service,
   - any matching `evidence_level`, `caveat`, or `advisory` text,
   - a short confirmation prompt: keep it, adjust it, or ask Traigent for a refreshed plan.
5. Record the user's confirmations and adjustments as a run-plan record. Use
   `references/run-plan.template.md` only as a capture format for the service
   payload and user decisions, not as a source of recommended settings. See
   `references/run-plan.txt2sql-example.md` for a filled text2SQL example of this
   capture format (the recommended values shown there came from the service, not
   from this skill).
6. Before launching, walk the preflight checklist in `references/preflight.md`.
   For program-level principles, see `references/optimization-principles.md`.
7. Mock dry-run first. The mock must be free/no-spend and should verify that the
   agent, dataset loader, scorer, and returned steps are wired.
8. Stop after the mock with a short readout: what executed, what did not execute,
   estimated cost if available, and the exact real-run command or SDK step that
   will run next. **If the mock fails** (agent, loader, or scorer unwired), do
   NOT present the real-run go prompt — fix the wiring first and re-mock.
9. Launch the real run only when the user explicitly says to go and the returned
   plan's cost cap is set. Execute the returned `steps[]`; do not substitute a
   locally generated run sequence.
10. After the run, hand control to Mode B (post-run next steps) with the run id
   and portal link.

### Confirmation Rules

- Defaults are confirmed, not silent. A user can approve the service plan as-is,
  but you still show every returned option group.
- If the user changes an option, ask Traigent for an updated plan when that
  change could affect later steps or cost. Treat manual edits as user overrides
  and label them that way in the run-plan record.
- If the service returns no plan, an incomplete plan, or a plan for the wrong
  task, do not patch it locally. Re-query with corrected context or stop.
- If prior runs exist, run Mode B first and pass its server recommendation
  into the plan request as context. The next-step decision still comes from the
  service. Fetch the guidance decision **at most once per planning cycle** — if you
  arrived at Mode A *from* Mode B, do not fetch it again; proceed to step 1
  with its payload as context.
- Keep content local unless the user approves egress. Summaries sent to the
  service should be minimal and should not include raw private examples by
  default.

### First Run Onboarding

If the user has not run Traigent before, ask whether they want to start with the
bundled text2SQL example or use their own agent. The example is useful because it
exercises the same thin-client loop: gather summary, fetch the service plan,
confirm options, mock dry-run, then real run on explicit approval.

Do not hard-code example models, knobs, or trial counts here. Fetch the example
plan from Traigent using the same protocol.

---

## Mode B — Post-Run Next Steps (Portal-Tracked)

Use this after every portal-tracked Traigent optimization run before planning the next one.

This is the canonical "what next" path for portal-tracked runs: fetch and follow the
server-owned next-step payload first. For offline/local runs with no service payload, fall
through to Mode C; for reading result fields or producing reports without making a decision, hand
off to `traigent-analyze-results`.

Fetch the next-step payload from the Traigent service; do not substitute markdown reasoning.

This mode is a thin client. Fetch the post-run payload, validate its decision
provenance, present the single authoritative action, then send that direction
into Mode A as context for a fresh service plan.

This mode is inert without the backend payload. If the command cannot fetch a
service response, report that directly and stop unless the user asks you to
retry. Retry **at most once**; if the second attempt also fails, fall through to
Mode C for local diagnosis instead of retrying again.

### Boundary

For portal-tracked runs handled by this mode, the decision comes from the
Traigent service. Do not maintain local next-action rules, derive
recommendations from local files, or infer what should happen next from
markdown.

Planner V2 is additive. Use it for newly enrolled lifecycles. Continue v1 only
for a lifecycle already pinned to v1; never silently fall back from a v2
controlled comparison to `next-steps`, and never pool v1 and v2 observations.

The public V2 command is intentionally static and opaque. Do not execute a
server-supplied shell fragment. For an executable decision, pass only its
opaque id to `traigent guidance execute --decision <opaque-id>` after the user
approves. The authenticated SDK resolves the private, scoped execution spec.
If the user asks for a different action, label that as a manual override and
request a fresh server decision.

### Protocol

> Pass the backend URL explicitly in portable scripts. Stored CLI credentials
> and `TRAIGENT_BACKEND_URL` / `TRAIGENT_API_URL` remain valid when supported.
>
> ```bash
> export TRAIGENT_API_KEY="uk_..."
> traigent guidance next RUN_ID --profile balanced --treatment policy_override \
>   --backend-url "https://portal.traigent.ai" --json
> ```
>
> For a controlled rules-versus-planner comparison, precommit both the arm and
> utility profile in the experiment manifest before the run. Request exactly
> that pair and require strict provenance:
>
> ```bash
> traigent guidance next RUN_ID --profile balanced --treatment rules_control \
>   --strict-experiment --backend-url "https://portal.traigent.ai" --json
> traigent guidance next RUN_ID --profile balanced --treatment policy_override \
>   --strict-experiment --backend-url "https://portal.traigent.ai" --json
> ```

1. Collect the completed run id and the portal `View` link.
   In SDK >= 0.18.1.dev2, `result.experiment_run_id` (and `result.experiment_id`) are
   populated directly on the optimize result object — use `result.experiment_run_id` as
   the `RUN_ID`. Do not ask the user to search logs; the value is on the result.
   ```python
   results = await my_func.optimize(max_trials=10)
   run_id = results.experiment_run_id   # available directly; pass this to guidance next
   ```
2. Fetch exactly one decision with
   `traigent guidance next RUN_ID --profile PROFILE --treatment TREATMENT --backend-url <url> --json`.
   The treatment is `rules_control` or `policy_override`; the profile is
   `quality_first`, `balanced`, or `cost_first`. Both must match the experiment
   manifest committed before outcomes were observed. Do not select either after
   seeing results or rely on mutable shell state to assign them.
3. Validate the exact public response before presenting it:
   - Require `schema_version`, `lifecycle_id`, `run_id`, `decision`, and `meta`;
     reject unknown top-level or nested fields and unknown enum values.
   - Join `run_id` to the request. Treat `lifecycle_id`, `decision.id`,
     `decision.certificate_ref`, and the evidence hash as opaque values.
   - Require `meta.requested_variant` and `meta.served_variant` to equal the
     precommitted treatment. Record `meta.selector_engine`, fallback reason,
     and policy, rule, calibration, and shield versions.
   - Require the decision's utility profile to equal the precommitted profile.
     A `policy_override` must have source `policy`, advantage label
     `certified_session_utility_advantage_no_kpi_guarantee`, an opaque
     certificate reference, and high evidence. This means the exact action has
     an HMAC-authenticated, empirically screened positive session-utility
     advantage on its stated support; it is not a product-KPI guarantee or
     proof of an independent issuer because the current attestation is symmetric.
   - Treat `rules_parity` with label `no_certified_override` as the normal case
     where no certified override applies and the safe rule action is retained;
     do not say the policy "agreed" with the rule. Treat `rules_fallback` as
     unavailable planner evidence, never as a policy-served sample, and retain
     its exact `meta.fallback_reason`: `policy_unavailable`, `calibration_unavailable`,
     `artifact_invalid`, `certificate_drift`, `exact_support_mismatch`, or
     `override_denied`. Report parity and fallback under the experiment's
     intention-to-treat protocol.
   - Consume only output already validated by `traigent guidance next` or
     `PlannerV2Client`. Do not hand-parse raw, stored, or mocked JSON: if it did
     not pass the SDK's exact-key, enum, category/variant, mode/source/selector,
     certificate, evidence-level, and cross-field checks, stop without a
     decision. In particular: parity is source `rules` with selector `policy`,
     a null certificate, medium evidence, and category equal to the baseline;
     fallback is requested/served `policy_override` with source/selector
     `rules`, a non-null fallback reason, and no certificate; pending WAIT is
     source `rules` with selector `safety`; STOP uses source/selector `safety`.
   - In strict experiments, fail closed on treatment/profile mismatch, missing
     provenance, fallback, malformed command, or an unavailable selector. Do
     not replace a rejected v2 decision with v1 guidance or local reasoning.
4. Present the returned decision without re-ranking it: category, action
   variant, templated rationale, advantage label, evidence level, treatment,
   selector engine, fallback status, version pins, and portal link. Never expand
   the opaque certificate or evidence reference into guessed internals.

   **If `decision.category=wait`**, require mode `pending_wait`,
   `decision.action.kind=none`, and an empty command. Present the rationale as
   the complete recommendation. Do not execute, prompt for another action, or
   immediately re-query; resume only after new evidence arrives.

   **If `decision.category=stop`**, require mode `safety_stop`,
   `decision.action.kind=none`, and an empty command. Stop the cycle. Reopen only
   through the v2 reopen operation with an explicit `new_artifact`, `budget`, or
   `operator` reason; a reopened child retains the assigned treatment and
   profile.

   ```bash
   traigent guidance reopen LIFECYCLE_ID --reason new_artifact \
     --expected-treatment TREATMENT --expected-profile PROFILE --json
   ```
5. Require action kind `cli`, a variant valid for the client-safe category, and
   the exact template `traigent guidance execute --decision DECISION_ID` for
   every operation other than WAIT/STOP. Reject extra arguments, shell
   operators, direct skill names, and raw optimization commands. Ask for
   confirmation, then run the static command with the opaque id only. Internal
   operation names appear only after authenticated private resolution.
6. Record execution through V2 receipts:
   - resolving the opaque decision creates the attempt, lease, reservation, and
     initial `started` event atomically;
   - a later `started` receipt is only a heartbeat that refreshes that same
     active attempt lease;
   - `submitted` requires an opaque `result_ref` and may include a successor run;
   - `started` is always `pending`; `submitted` may be `pending`, `verified`, or
     `rejected`; `failed` and `skipped` are always `rejected`;
   - `verification_status=pending` is not completion. A mutation remains
     awaiting verification until a registered revision is consumed by a
     successor run. Never translate `submitted` into `verified` locally.
   Use the explicit receipt surface; do not call the endpoint with ad-hoc shell
   text:

   ```bash
   traigent guidance receipt --lifecycle LIFECYCLE_ID \
     --decision DECISION_ID --attempt ATTEMPT_ID --status submitted \
     --result-ref RESULT_REF --successor-run SUCCESSOR_RUN_ID --json
   ```
7. After a verified action, loop back to Mode A with the run id, portal link,
   and opaque decision id. The next paid run still requires a fresh service
   plan, mock dry-run, cost approval, and explicit go. WAIT or STOP ends the
   cycle as described above.

### Existing V1 Lifecycle Compatibility

Use this only when the service says the existing lifecycle is pinned to v1 and
the work is not part of a V2 efficacy comparison:

```bash
traigent next-steps RUN_ID --backend-url <url> --json
```

For its legacy rules-versus-policy experiment, the corresponding explicit
forms remain `--guidance-variant rules` and `--guidance-variant policy` with
`--strict-experiment`. Require `guidance_meta.served_variant`, the actual
`engine`, fallback reason, evidence-snapshot hash, top-level `decision`, an
empty `next_steps` list, and a single authoritative action. Never use the first
`next_steps[]` compatibility row in a controlled comparison. Run only the
command template the service returns for this pre-existing v1 lifecycle, and
record its execution receipt. Do not enroll a new lifecycle in v1.

### Presentation Rules

- Use Traigent's words for the recommendation. You may summarize for readability,
  but do not change the ordering or imply stronger support than the payload gives.
- Present the single authoritative v2 decision and its templated rationale. Do
  not reconstruct hidden evidence from local files.
- Never treat `served_variant=policy_override` as proof that an override ran;
  require mode `policy_override`, source `policy`, the exact
  `certified_session_utility_advantage_no_kpi_guarantee` label, and an opaque
  certificate reference.
- High evidence means a valid HMAC-authenticated empirical override or a safety-complete stop. Medium
  means complete rules/parity evidence. Low is allowed only for a
  non-mandatory fallback or wait; never use it to promote.
- Always include the portal link when available. The portal is the durable record
  for best performers, tradeoffs, parameter importance, and decision context.
- If the run is absent from the portal, treat that as a registration or
  connectivity issue. Do not invent a next-step decision from partial local data.
- Keep raw examples, traces, and private content local unless the user explicitly
  approves egress.
- Traigent recommendations (including "compare with baseline before promotion") are
  advisory, not promotion authorizations. Promotion requires candidate-vs-incumbent
  evaluation on the holdout slice. If the repo already has a holdout mechanism, present
  it as that repo's implementation of this general rule, not as something Traigent
  mandated in that exact form.

### Handoff Reference

Planner V2 resolves the private execution spec after the opaque static command
is approved. The resolved spec may route to the current skill names below;
reject a stale or unavailable skill instead of guessing what it meant. These
are handoff labels, not a local decision menu:

- evaluation-set scoring -> `traigent-dataset-curate`
- dataset curation -> `traigent-dataset-curate`
- hard-example reflection -> `traigent-dataset-curate`
- evaluator review -> `traigent-eval-audit`
- evaluator repair -> `traigent-eval-build`
- optimization run -> `traigent-optimize-run`
- holdout validation -> `traigent-ci-safety-gate`
- safety gate setup -> `traigent-ci-safety-gate`

---

## Mode C — Offline / Local Diagnosis

Use this mode after an offline/local Traigent optimization run (`offline=True` or no backend
access), or when a portal run's service guidance decision is unavailable and you need to form a
local hypothesis from evidence. It also applies when the service has already flagged local evidence
for inspection and the user asks:

- "results are flat/noisy/negative"
- "which knob mattered locally?"
- "should I expand or narrow the space?"
- "what do I do with weak examples?"

The goal is to choose the next single local hypothesis, not to change every part of the system at
once.

### Read the Evidence First

Start with the local run object and existing analysis skills. `traigent-analyze-results` covers
result fields in depth, and `traigent-analyze-variable-importance` covers richer importance reporting.
Use this mode to form the local next hypothesis after those facts are known.

For a portal-tracked run, first fetch the service-owned next-step payload through
Mode B. If that payload is unavailable, or if it flags local evidence that needs
diagnosis, keep the service limitation visible and use the local facts below as a fallback or
supporting diagnosis:

- `confidence` - keep low/medium confidence visible; do not upgrade it based on intuition.
- `evidence[].summary` - use backend summaries only when they are actually present in the service
  payload; otherwise use local result fields.
- local result fields - identify whether the issue is flat scores, noisy examples, high cost, thin
  samples, a dominated winner, or a narrow knob.

```python
from traigent.utils.insights import get_optimization_insights
from traigent.utils.importance import ParameterImportanceAnalyzer

print(f"stop_reason={results.stop_reason}")
print(f"best_config={results.best_config}")
print(f"trial_count={len(results.trials)}")
print(f"total_cost={results.total_cost}")

insights = get_optimization_insights(results)
print(insights.get("performance_summary", {}))
print(insights.get("parameter_insights", {}))

analyzer = ParameterImportanceAnalyzer(objective="accuracy")
importance = analyzer.analyze_variance_based(results.trials)
print(analyzer.get_top_parameters(importance, top_k=5))
```

If importance is empty, do not infer that no knob matters. Common reasons are too few successful trials, flat objective variance, missing objective metrics, or a configuration space that did not vary enough.

### Example-Side Evidence

<!-- PROTECTED -->
Use example-side evidence when the aggregate score hides where the candidate wins or fails. `ExampleInsightsClient` requires a Traigent account/backend and returns scoring metadata only: example ids, sample counts, algorithm version, and scored flags. It does not expose proprietary difficulty, informativeness, ambiguity, or latent feature-vector values. The ranked and flagged "examples to review" surface (`analytics_get_example_insights` / `GET /api/v1/analytics/runs/{run_id}/example-insights`) is likewise non-signal: it ranks by review urgency and provides enum flags and a suggested action — never raw scores or hidden feature values.
<!-- /PROTECTED -->

> **Import note (verified against SDK 0.18.x):** `ExampleInsightsClient` ships in the core SDK at `traigent.analytics` — no separate install required. The module's own `DeprecationWarning` points at the separate `traigent-analytics` plugin, but that plugin does not export `ExampleInsightsClient` (`from traigent_analytics import ExampleInsightsClient` raises `ImportError`); use the core import below and ignore the warning for this class. **Caveat if you HAVE installed the plugin:** the core shim then defers to the plugin and stops exposing this class, so the import below itself raises `ImportError` — uninstall the plugin or use the deep import `from traigent.analytics.example_insights import ExampleInsightsClient` (works with or without the plugin, verified).

```python
from traigent.analytics import ExampleInsightsClient

async def fetch_example_metadata(run_id: str):
    async with ExampleInsightsClient(
        backend_url="https://portal.traigent.ai",
        timeout=60.0,
    ) as client:
        job = await client.compute_scores(experiment_run_id=run_id)
        status = await client.get_job_status(job_id=job["job_id"])
        scores = await client.get_example_scores(experiment_run_id=run_id)
        quality = await client.get_dataset_quality(experiment_run_id=run_id)
        return {"status": status, "scores": scores, "quality": quality}
```

When aggregate scores hide where the candidate wins or fails, pull the ranked "examples to review" rows: use the `analytics_get_example_insights` MCP tool (or the `GET /api/v1/analytics/runs/{run_id}/example-insights` endpoint). Work through rows in `review_priority` order (critical first) and use each row's `suspicious_flags` and `recommended_action` to choose the next iteration — these are coarse enum signals, not hidden numeric scores. See `traigent-dataset-curate` for the flag-to-action guide.

Backend-only report surfaces, each requiring a Traigent account/backend:

- `GET /api/v1/experiment-runs/runs/{run_id}/report-payload`: winner, trade-off, and stability insights.
- `/api/v1/optimization-comparisons`: cross-run comparison across candidate runs.
- Example-scoring compute, scores, and dataset-quality endpoints: scoring status and scoring metadata.
- `GET /api/v1/analytics/runs/{run_id}/example-insights`: ranked and flagged examples to review (IP-safe: review_priority, suspicious_flags, recommended_action).

### Next-Step Decision Table

| Symptom | Likely read | Ranked next action |
|---|---|---|
| Flat scores everywhere | Evaluation dataset is too easy, objective is saturated, or the space lacks meaningful variation | First rule out rerun noise (`traigent-analyze-results` → "Is the Delta Real?" — see the note below); then synthesize harder examples with `traigent-dataset-curate`; add discriminating cases; then re-run a small grid |
| High variance across repetitions | Evaluator or model behavior is noisy | Rule out rerun noise first (`traigent-analyze-results` → "Is the Delta Real?" — see the note below): a single-cell delta under ~10 pp at n=40 is unreportable. Then raise repetitions, use statistical aggregation, and audit the evaluator with `traigent-eval-audit`. A server-side ACET evaluator-audit action (computed from the run's tensor) is coming as a next-step option — prefer it when available. |
| One knob dominates | The useful region is narrower than the current space | Narrow that knob's range; add structural knobs with `traigent-optimize-config-space` or `traigent-optimize-composite-knobs` |
| Winner ties baseline | Objective weights or threshold may not reflect the product decision | Revisit objective weights with `traigent-eval-choose-metric`; inspect holdout slices before changing the space |
| `stop_reason` is budget-bound | Search stopped before enough evidence accumulated | Adjust budget, cheaper models, max trials, or algorithm with `traigent-optimize-run` |
| Weak examples identified | The same examples fail across good configs | Feed those examples into guided optimization and add a heldout check |

> **Before treating a flat or noisy result as signal, rule out rerun noise.** See
> `traigent-analyze-results` → *"Is the Delta Real?"*: the same config on the same data moves
> ±5–10 pp across days at n=40 (same-config SD ≈ `50/√k` pp at p≈0.5), so a single-cell delta
> under ~10 pp is unreportable, pooling ≥4 cells only halves the noise, and numbers measured in
> different sessions/days must never be cross-compared. Claim a win only when a bootstrap CI on
> the difference excludes zero — a "flat" or "high-variance" result is often just this floor.

Use weak examples as evidence, not as a replacement for a holdout.

```python
weak_examples = [
    ("question text", "expected answer", "candidate answer"),
]

results = await answer.optimize_with_guidance(
    provider=provider,
    weak_examples=weak_examples,
    max_trials=8,
)
```

`optimize_with_guidance` is a method on the decorated optimized function. Keep the provider and rewrite settings project-specific, and confirm the new candidate still improves on a heldout slice.

This is a **paid real run** — the same gate as any other applies: dry-run/mock first, present the cost estimate, and get explicit user approval before executing (see the `traigent` lifecycle skill).

Before iterating, note that flat/negative scores can also mean: (a) the base model
isn't capable enough — structural knobs fix *form*, not reasoning the model lacks;
if a stronger/SOTA model is available, add it to the search (model capability is
itself a lever on hard tasks); and (b) a genuine difficulty/annotation ceiling —
after the metric is validated and knobs are complete, if even a strong model fails
the residual items, the ceiling is the data (report it / clean degenerate
references), not more tuning. Distinguish both from "dataset too easy".

### One Iteration = One Hypothesis

Change one thing per round. Good iteration statements look like:

- "Scores are flat because the evaluation dataset lacks hard negatives; add 30 hard negatives."
- "Variance is high because the LLM judge flips on borderline cases; raise repetitions and demote to statistical aggregation."
- "Temperature dominates; narrow temperature and add a retrieval-depth structural knob."

For each round:

1. Write the hypothesis.
2. Make one change.
3. Re-run on the same holdout.
4. Compare to the pinned baseline and previous candidate.
5. Keep a tiny iteration log.

Use `references/iteration-log-template.md` as the 10-line per-iteration log.

**Stop condition (mandatory):** stop iterating and report to the user when any
of these hold — two consecutive rounds with no heldout improvement, the cost
budget or sample quota is exhausted, or the user's goal is met. Never start
another paid round after a stop condition fires without the user's explicit
go-ahead. Iteration is a loop with an exit, not a background process.

### Claim Scope

Iteration decisions are local to the current evaluation dataset, holdout, objective, evaluator, configuration space, and budget. A better next action on one slice does not imply the same action is best after the dataset, evaluator, model provider, or objective weights change.

---

## See Also

- `traigent-optimize-run` - execute approved optimization runs; adjust algorithms, trial budgets, and cost controls.
- `traigent-dataset-curate` - build or improve local evaluation data; follow a returned curation command.
- `traigent-dataset-curate` - join server-flagged example ids to local content.
- `traigent-eval-audit` - diagnose noisy or biased judge metrics; follow a returned evaluator command.
- `traigent-ci-safety-gate` - follow a returned gate command.
- `traigent-analyze-results` - field-level result reading and stop-reason interpretation.
- `traigent-analyze-variable-importance` - deeper tuned-variable importance and video-card output.
- `traigent-optimize-config-space` - narrow or expand tuned variables.
- `traigent-optimize-composite-knobs` - add structural knobs when scalar knobs are not enough.

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

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
