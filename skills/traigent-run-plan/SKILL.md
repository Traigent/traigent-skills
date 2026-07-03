---
name: traigent-run-plan
description: "Fetch the Traigent service run-plan before every optimization run, present objectives/models/knobs/search/budget/offline options one by one, apply preflight and program-level optimization principles, confirm or adjust them with the user, mock dry-run first, and launch only on the user's explicit go. The plan and next-step decision come from Traigent, not local markdown logic."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.1.1"
---

# Traigent Run Plan Thin Client

## When to Use

Requires `traigent>=0.16.0`.

Use this before designing or launching any Traigent optimization run.

This skill is a thin client. It gathers the minimum run context, asks the
Traigent service for an allowlisted plan, presents that payload to the user, and
executes only the returned steps after the user approves. Do not invent or
improve the plan locally.

## Boundary

The recommended plan comes from the Traigent service via `traigent plan` or the
MCP tool `get_optimization_plan`. The returned payload is advisory and currently
static guidance: expect `phase` such as `P1_STATIC`, plus `evidence_level`,
`caveat`, and `advisory`.

This requires an SDK build that ships the optimization-plan tool (the `traigent
plan` CLI / `get_optimization_plan` MCP tool). If your installed SDK does not
expose it yet, tell the user the plan service is not available in this build and
fall back to `traigent recommend` for knob recommendations (see
`traigent-configuration-space`) — never fabricate a plan locally.

Do not embed local planning intelligence in this skill:

- Do not choose or rank models, knobs, algorithms, budgets, or option order in markdown.
- Do not compute plan-quality bands, search-space rules, or recommended trial counts locally.
- Do not add a replacement plan if the service omits one. Ask the service again with clearer context or stop for user input.
- Do not treat the advisory plan as proof that a real run will improve. The mock and heldout results remain the evidence.

## Protocol

1. Gather a short summary from the user or project files:
   - task description and agent entrypoint,
   - dataset size and holdout split,
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
10. After the run, hand control to `traigent-next-run` with the run id and portal
   link.

## Confirmation Rules

- Defaults are confirmed, not silent. A user can approve the service plan as-is,
  but you still show every returned option group.
- If the user changes an option, ask Traigent for an updated plan when that
  change could affect later steps or cost. Treat manual edits as user overrides
  and label them that way in the run-plan record.
- If the service returns no plan, an incomplete plan, or a plan for the wrong
  task, do not patch it locally. Re-query with corrected context or stop.
- If prior runs exist, call `traigent-next-run` first and pass its server
  recommendations into the plan request as context. The next-step decision still
  comes from the service. Call it **at most once per planning cycle** — if you
  arrived here *from* `traigent-next-run`, do not call it again; proceed to
  step 1 with its payload as context.
- Keep content local unless the user approves egress. Summaries sent to the
  service should be minimal and should not include raw private examples by
  default.

## First Run Onboarding

If the user has not run Traigent before, ask whether they want to start with the
bundled text2SQL example or use their own agent. The example is useful because it
exercises the same thin-client loop: gather summary, fetch the service plan,
confirm options, mock dry-run, then real run on explicit approval.

Do not hard-code example models, knobs, or trial counts here. Fetch the example
plan from Traigent using the same protocol.

## See Also

`traigent-next-run` - fetch server next-step recommendations after a run.
`traigent-run-optimization` - execute approved optimization runs.
`traigent-curate-dataset` - build or improve local evaluation data.
`traigent-reflect-hard-examples` - join server-flagged example ids to local content.

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
