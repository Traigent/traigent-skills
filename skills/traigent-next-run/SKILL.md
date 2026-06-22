---
name: traigent-next-run
description: "After every Traigent run, fetch server next-step recommendations with `traigent next-steps RUN_ID --json`, present the recommendations and portal link, then loop back to `traigent-run-plan`. The next-step decision comes from Traigent, not local markdown logic."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.1"
---

# Traigent Next Run Thin Client

## When to Use

Requires `traigent>=0.16.0`.

Use this after every Traigent optimization run before planning the next one.

This skill is a thin client. It fetches the next-step payload from Traigent,
presents it to the user, and sends the user's chosen direction back into
`traigent-run-plan` as context for a fresh service plan.

## Boundary

The next-step decision comes from the Traigent service. Do not maintain local
next-action rules, and do not infer keep/drop/add recommendations from markdown.
If the service payload is unavailable or incomplete, say that directly and
either retry or ask the user for permission to inspect local artifacts.

## Protocol

1. Collect the completed run id and the portal `View` link printed by the SDK or
   shown in the Traigent portal.
2. Fetch next steps with `traigent next-steps RUN_ID --json`.
3. Present the returned payload without re-ranking it:
   - server recommendations,
   - portal link,
   - best config or comparison fields if present,
   - any evidence level, caveat, advisory, or confidence text returned by the service,
   - any requested follow-up actions.
4. Ask the user which returned recommendation to pursue. If the user wants a
   change outside the payload, label it as a manual override and ask whether to
   request a refreshed recommendation.
5. Loop back to `traigent-run-plan`, passing the run id, portal link, and the
   selected server recommendation as context. The next run still requires a fresh
   service plan, option-by-option confirmation, mock dry-run, and explicit go.

## Presentation Rules

- Use Traigent's words for the recommendation. You may summarize for readability,
  but do not change the ordering or imply stronger evidence than the payload gives.
- Always include the portal link when available. The portal is the durable record
  for best performers, tradeoffs, parameter importance, and decision context.
- If the run is missing from the portal, treat that as a registration or
  connectivity issue. Do not invent a next-step decision from partial local state.
- Keep raw examples, traces, and private content local unless the user explicitly
  approves egress.

## See Also

`traigent-run-plan` - fetch and confirm the next service plan.
`traigent-reflect-hard-examples` - locally inspect examples that the service has flagged.
`traigent-analyze-results` - read local result objects when the user asks for inspection.
