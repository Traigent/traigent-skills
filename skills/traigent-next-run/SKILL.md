---
name: traigent-next-run
description: "After every Traigent run, fetch the server-owned artifact-lifecycle and next-step payload with `traigent next-steps RUN_ID --json`, present artifact states plus the single recommended operation and portal link, then loop back to `traigent-run-plan`. The decision comes from Traigent, not local markdown logic."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.2"
---

# Traigent Next Run Thin Client

## When to Use

Requires `traigent>=0.16.0`.

Use this after every Traigent optimization run before planning the next one.

This skill is a thin client. It fetches the post-run payload from the Traigent
service, presents it to the user, and sends the selected service direction back
into `traigent-run-plan` as context for a fresh service plan.

When the backend returns it, that payload includes the server-owned
ARTIFACT-LIFECYCLE view: per-artifact state for DATASET, EVALUATOR, and AGENT,
plus one recommended next OPERATION with a command template, evidence level, and
any caveat. This view needs a Traigent backend; the skill is inert without the
service payload.

## Boundary

The next-step decision comes from the Traigent service. Do not maintain local
next-action rules, derive artifact state, or infer keep/drop/add recommendations
from markdown. If the service payload is unavailable or incomplete, say that
directly and either retry or ask the user for permission to inspect local
artifacts.

The service owns cross-artifact dependencies. For example, the service will not
recommend promoting an agent until its dataset and evaluator are trusted and it
has passed holdout. Treat that as descriptive context for what the service
enforces, never as a local rule this skill executes.

## Artifact-Lifecycle View

Fetch the artifact-lifecycle view from the Traigent service through the
supported next-steps command. The service may return:

- `artifact_states`: DATASET, EVALUATOR, and AGENT state labels, caveats, and
  supporting evidence text. Example state vocabularies may include dataset
  empty/populated/scored/trusted/degraded/broken, evaluator
  undefined/defined/audited/trusted/noisy/broken, and agent
  baseline/optimizing/optimized/validated_on_holdout/promotable.
- `next_step`: exactly one server-recommended operation, its command template,
  evidence level, caveat, and any advisory text.

Present those fields using the service's words. Do not fill in missing states,
choose a different operation, or strengthen the evidence level.

## Protocol

1. Collect the completed run id and the portal `View` link printed by the SDK or
   shown in the Traigent portal.
2. Fetch next steps with `traigent next-steps RUN_ID --json`.
3. Present the returned payload without re-ranking it:
   - `artifact_states` for DATASET, EVALUATOR, and AGENT when present,
   - the single `next_step` operation,
   - the `next_step` command template,
   - portal link,
   - best config or comparison fields if present,
   - any evidence level, caveat, advisory, or confidence text returned by the service,
   - any requested follow-up actions.
4. Ask the user whether to pursue the returned operation. If the user wants a
   change outside the payload, label it as a manual override and ask whether to
   request a refreshed recommendation.
5. Run only the command template the service returns, and only after the user
   confirms it.
6. Loop back to `traigent-run-plan`, passing the run id, portal link, and the
   selected server operation as context. The next run still requires a fresh
   service plan, option-by-option confirmation, mock dry-run, and explicit go.

## Presentation Rules

- Use Traigent's words for the recommendation. You may summarize for readability,
  but do not change the ordering or imply stronger evidence than the payload gives.
- Present the returned `artifact_states` and single `next_step` verbatim enough
  that the operation, command template, evidence level, and caveat remain intact.
- Always include the portal link when available. The portal is the durable record
  for best performers, tradeoffs, parameter importance, and decision context.
- If the run is missing from the portal, treat that as a registration or
  connectivity issue. Do not invent a next-step decision from partial local state.
- If the artifact-lifecycle fields are absent, report that the backend did not
  provide them in this payload. Do not synthesize a lifecycle view from local
  files.
- Keep raw examples, traces, and private content local unless the user explicitly
  approves egress.

## Operation Handoff Reference

Follow whatever operation the service returns. These mappings are only handoff
labels for a returned operation, not a local menu:

- score or curate -> `traigent-curate-dataset`
- reflect -> `traigent-reflect-hard-examples`
- audit -> `traigent-evaluator-audit`
- run -> `traigent-run-optimization`
- gate -> `traigent-ci-safety-gate`

## See Also

`traigent-run-plan` - fetch and confirm the next service plan.
`traigent-curate-dataset` - follow a returned score or curate operation.
`traigent-reflect-hard-examples` - locally inspect examples that the service has flagged.
`traigent-evaluator-audit` - follow a returned audit operation.
`traigent-run-optimization` - follow a returned run operation.
`traigent-ci-safety-gate` - follow a returned gate operation.
`traigent-analyze-results` - read local result objects when the user asks for inspection.
