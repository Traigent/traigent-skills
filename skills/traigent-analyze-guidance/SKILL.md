---
name: traigent-analyze-guidance
description: "What should this Traigent optimization run be, and what next? Three modes: (A) pre-run — fetch the service run-plan, present objectives/models/knobs/search/budget/offline options, apply preflight; (B) post-run, portal-tracked — fetch `traigent next-steps RUN_ID --json`, present posture.summary_text plus the single returned command template; (C) offline/local fallback — diagnose flat/noisy/negative local results, which knob mattered, example evidence, form the next iteration hypothesis when offline=True or no service payload. Portal-tracked decisions come from Traigent, never local markdown."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.0.2"
---

# Traigent Analyze Guidance

## When to Use

Requires `traigent>=0.16.0`.

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

## Mode Arbitration

| Situation | Mode |
|---|---|
| About to design or launch a run (any run, always) | **A** — fetch and confirm the service run-plan |
| A portal-tracked run just completed | **B** — fetch `traigent next-steps RUN_ID --json` first |
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
- If prior runs exist, run Mode B first and pass its server recommendations
  into the plan request as context. The next-step decision still comes from the
  service. Fetch next-steps **at most once per planning cycle** — if you
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

This mode is a thin client. It fetches the post-run payload from the Traigent
service, presents the returned `posture.summary_text` and the single recommended
next action to the user, and sends the selected service direction back into
Mode A as context for a fresh service plan.

The service response may include an optional top-level `posture` object:

- `posture.summary_text`: server-generated, redacted prose for the run.
- `posture.generated_at`: timestamp for that prose.

This mode is inert without the backend payload. If the command cannot fetch a
service response, report that directly and stop unless the user asks you to
retry. Retry **at most once**; if the second attempt also fails, fall through to
Mode C for local diagnosis instead of retrying again.

### Boundary

For portal-tracked runs handled by this mode, the decision comes from the Traigent service. Do not
maintain local next-action rules, derive recommendations from local files, or infer what should
happen next from markdown.

Only execute commands returned by the service. If the user asks for a change
outside the payload, label it as a manual override and ask whether to request a
fresh recommendation.

### Protocol

> For the most portable `traigent next-steps` invocation, pass the backend URL on
> the command itself. Older `next-steps` CLI builds ignored `TRAIGENT_BACKEND_URL`;
> newer builds also read `TRAIGENT_BACKEND_URL` / `TRAIGENT_API_URL` and stored
> CLI credentials, but `--backend-url` works across both paths. Without a cloud/dev
> backend, the command falls back to `http://localhost:5000` and fails before it
> can fetch a service payload.
>
> ```bash
> export TRAIGENT_API_KEY="uk_..."
> traigent next-steps RUN_ID --backend-url "https://portal.traigent.ai" --json
> ```

1. Collect the completed run id and the portal `View` link.
   In SDK >= 0.18.1.dev2, `result.experiment_run_id` (and `result.experiment_id`) are
   populated directly on the optimize result object — use `result.experiment_run_id` as
   the `RUN_ID`. Do not ask the user to search logs; the value is on the result.
   ```python
   results = await my_func.optimize(max_trials=10)
   run_id = results.experiment_run_id   # available directly; pass this to next-steps
   ```
2. Fetch next steps with `traigent next-steps RUN_ID --backend-url <url> --json`.
   If `traigent next-steps --help` lists `(env: TRAIGENT_BACKEND_URL / TRAIGENT_API_URL)`,
   an env-var-only call is also valid for that SDK, but keep the explicit flag in
   portable docs and scripts.
3. Present the returned payload without re-ranking it:
   - `posture.summary_text`, when present (show this first),
   - `posture.generated_at`, when present,
   - the first returned `next_steps[]` item, **if `next_steps` is non-empty**,
   - `next_steps[].action.command_template`,
   - the returned rationale for that next action,
   - portal link,
   - best config or comparison fields if present,
   - any caveat, advisory, or confidence text returned by the service,
   - any requested follow-up actions.

   **If `next_steps` is an empty list** (normal for very small or low-coverage runs),
   present `posture.summary_text` as the complete guidance for this run and do not
   fabricate step recommendations. Tell the user there are no step recommendations for
   this run and suggest they expand coverage (more trials or more dataset examples) before
   the next run.

4. Ask the user whether to pursue the returned command template. If `next_steps` is empty
   or has no command template, ask whether to retry the backend request after expanding
   run coverage.
5. Run only the command template the service returns, and only after the user
   confirms it.
6. Loop back to Mode A, passing the run id, portal link, posture
   prose, and selected service action as context. The next run still requires a
   fresh service plan, option-by-option confirmation, mock dry-run, and explicit
   go.

### Presentation Rules

- Use Traigent's words for the recommendation. You may summarize for readability,
  but do not change the ordering or imply stronger support than the payload gives.
- Present `posture.summary_text` as opaque server prose. Do not expand it into
  internal fields or local reasoning.
- Present the single returned next action with its rationale and
  `next_steps[].action.command_template`.
- Always include the portal link when available. The portal is the durable record
  for best performers, tradeoffs, parameter importance, and decision context.
- If the run is absent from the portal, treat that as a registration or
  connectivity issue. Do not invent a next-step decision from partial local data.
- If the posture field is absent, report that the backend did not provide a
  posture summary in this payload. Do not synthesize one from local files.
- Keep raw examples, traces, and private content local unless the user explicitly
  approves egress.
- Traigent recommendations (including "compare with baseline before promotion") are
  advisory, not promotion authorizations. Promotion requires candidate-vs-incumbent
  evaluation on the holdout slice. If the repo already has a holdout mechanism, present
  it as that repo's implementation of this general rule, not as something Traigent
  mandated in that exact form.

### Handoff Reference

Follow whatever command template the service returns. These mappings are only
handoff labels for a returned action, not a local menu:

- dataset curation -> `traigent-dataset-curate`
- hard-example reflection -> `traigent-dataset-curate`
- evaluator review -> `traigent-eval-audit`
- evaluator repair -> `traigent-eval-audit` (service `improve_evaluator` action; present the returned action verbatim, do not repair locally)
- optimization run -> `traigent-optimize-run`
- safety gate setup -> `traigent-ci-safety-gate`

---

## Mode C — Offline / Local Diagnosis

Use this mode after an offline/local Traigent optimization run (`offline=True` or no backend
access), or when a portal run's service next-steps payload is unavailable and you need to form a
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
<!-- contract: path /api/v1/analytics/runs/{run_id}/example-insights in traigent.cloud.analytics_client @ SDK 0.21.0 -->

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
| Flat scores everywhere | Evaluation dataset is too easy, objective is saturated, or the space lacks meaningful variation | Synthesize harder examples with `traigent-dataset-curate`; add discriminating cases; then re-run a small grid |
| High variance across repetitions | Evaluator or model behavior is noisy | Raise repetitions, use statistical aggregation, and audit the evaluator with `traigent-eval-audit`. A server-side ACET evaluator-audit action (computed from the run's tensor) is coming as a next-step option — prefer it when available. |
| One knob dominates | The useful region is narrower than the current space | Narrow that knob's range; add structural knobs with `traigent-optimize-config-space` or `traigent-optimize-composite-knobs` |
| Winner ties baseline | Objective weights or threshold may not reflect the product decision | Revisit objective weights with `traigent-eval-choose-metric`; inspect holdout slices before changing the space |
| `stop_reason` is budget-bound | Search stopped before enough evidence accumulated | Adjust budget, cheaper models, max trials, or algorithm with `traigent-optimize-run` |
| Weak examples identified | The same examples fail across good configs | Feed those examples into guided optimization and add a heldout check |

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
