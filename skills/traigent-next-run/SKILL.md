---
name: traigent-next-run
description: "After every Traigent run, fetch the server-owned posture and next-step payload with `traigent next-steps RUN_ID --json`, present the opaque prose summary plus the single returned command template and rationale, then loop back to `traigent-run-plan`. The decision comes from Traigent, not local markdown logic."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.4"
---

# Traigent Next Run Thin Client

## When to Use

Requires `traigent>=0.16.0`.

Use this after every Traigent optimization run before planning the next one.

This skill is a thin client. It fetches the post-run payload from the Traigent
service, presents the returned `posture.summary_text` and the single recommended
next action to the user, and sends the selected service direction back into
`traigent-run-plan` as context for a fresh service plan.

The service response may include an optional top-level `posture` object:

- `posture.summary_text`: server-generated, redacted prose for the run.
- `posture.generated_at`: timestamp for that prose.

The skill is inert without the backend payload. If the command cannot fetch a
service response, report that directly and stop unless the user asks you to
retry.

## Boundary

The next-step decision comes from the Traigent service. Do not maintain local
next-action rules, derive recommendations from local files, or infer what should
happen next from markdown.

Only execute commands returned by the service. If the user asks for a change
outside the payload, label it as a manual override and ask whether to request a
fresh recommendation.

## Protocol

> **`TRAIGENT_BACKEND_URL` must be set before any `traigent next-steps` call.** The CLI
> defaults to `http://localhost:5000`; without the env var or the `--backend-url` flag
> pointing to the cloud/dev endpoint, the command fails with a connection-refused error.
>
> ```bash
> export TRAIGENT_BACKEND_URL="https://api.traigent.ai"   # or pass --backend-url <url>
> export TRAIGENT_API_KEY="uk_..."
> ```

1. Collect the completed run id and the portal `View` link.
   In SDK >= 0.18.1.dev2, `result.experiment_run_id` (and `result.experiment_id`) are
   populated directly on the optimize result object — use `result.experiment_run_id` as
   the `RUN_ID`. Do not ask the user to search logs; the value is on the result.
   ```python
   results = await my_func.optimize(max_trials=10)
   run_id = results.experiment_run_id   # available directly; pass this to next-steps
   ```
2. Fetch next steps with `traigent next-steps RUN_ID --json` (add `--backend-url <url>`
   if `TRAIGENT_BACKEND_URL` is not set).
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
6. Loop back to `traigent-run-plan`, passing the run id, portal link, posture
   prose, and selected service action as context. The next run still requires a
   fresh service plan, option-by-option confirmation, mock dry-run, and explicit
   go.

## Presentation Rules

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

## Handoff Reference

Follow whatever command template the service returns. These mappings are only
handoff labels for a returned action, not a local menu:

- dataset curation -> `traigent-curate-dataset`
- hard-example reflection -> `traigent-reflect-hard-examples`
- evaluator review -> `traigent-evaluator-audit`
- optimization run -> `traigent-run-optimization`
- safety gate setup -> `traigent-ci-safety-gate`

## See Also

`traigent-run-plan` - fetch and confirm the next service plan.
`traigent-curate-dataset` - follow a returned curation command.
`traigent-reflect-hard-examples` - locally inspect examples that the service has flagged.
`traigent-evaluator-audit` - follow a returned evaluator command.
`traigent-run-optimization` - follow a returned run command.
`traigent-ci-safety-gate` - follow a returned gate command.
`traigent-analyze-results` - read local result objects when the user asks for inspection.

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

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
