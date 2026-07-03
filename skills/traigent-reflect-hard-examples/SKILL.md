---
name: traigent-reflect-hard-examples
description: "Run the local content-reflection loop after Traigent has flagged hard or broken example IDs: fetch server-selected IDs/categories, map them to local example content with `traigent report-example-map` or `build_example_content_map`, inspect expected-vs-actual locally, classify the failure pattern, and take one server-suggested action without exposing raw content unless approved."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.1"
---

# Reflect On Hard Examples

## When to Use

Requires `traigent>=0.16.0`.

Use this after a Traigent run when the server has identified hard, weak, or
broken examples and the user wants to improve the agent, prompt, skill, or
dataset using local example content.

This is the content-reflection loop. Traigent can identify safe example ids and
coarse categories, but raw example content stays local. The skill joins those ids
to local inputs, expected outputs, and actual outputs, then takes one
server-suggested action.

## Boundary

The server selects the examples and recommends the next action. This skill does
not decide which examples are hard.

- Fetch flagged ids and coarse categories from server surfaces such as
  `traigent next-steps RUN_ID --json` and example-scoring dataset-quality output.
- Do not rank, expand, or replace the flagged id list locally.
- Do not send raw example text, expected answers, actual answers, traces, or
  customer content to Traigent unless the user explicitly approves that egress.
- If the server returns no flagged ids, stop or ask the user whether to run the
  server-side scoring/recommendation flow. Do not make a local hard-example list.
- Take one action from the server recommendations. If the user wants another
  action, label it as a manual override or request refreshed next steps.

## Inputs

- Run id.
- Portal link, if available.
- Path to the local evaluation dataset.
- Local run artifacts or result rows that include actual outputs per example.
- Server next-step or example-scoring payload with safe example ids, coarse
  categories, and recommended actions.

## Protocol

1. Fetch the server payload. Prefer `traigent next-steps RUN_ID --json`; if the
   flow is already in example-scoring, use the server's dataset-quality or
   curation output. Record the returned ids, coarse categories, and recommended
   actions exactly.
2. Build a local example-content map:
   - Use `traigent report-example-map` for a local-only file map from dataset
     rows to stable example ids.
   - Use the SDK helper `build_example_content_map` when already inside Python
     automation.
3. Join only the server-flagged ids to local content. For each matched id, read:
   - input,
   - expected output,
   - actual output from the run artifact,
   - coarse category returned by the server,
   - any local metadata such as split, source, or reviewer note.
4. Classify the local failure pattern from expected-vs-actual. Keep the
   classification factual and content-local, for example: label mismatch,
   missing context, retrieval miss, tool-use failure, output-format failure,
   prompt ambiguity, evaluator issue, or agent-code bug. If the classification
   is "evaluator issue", the server next-step may be a server-side evaluator
   audit (ACET-based, read-only) or `improve_evaluator` (lockbox repair). Present
   the server action verbatim and hand off to `traigent-evaluator-audit`; do
   not manually re-rank or re-score evaluators.
5. Pick exactly one server-suggested action and ask the user to approve it:
   - `ExampleSynthesizer` with `GuidanceAction.GENERATE_HARDER`,
   - `ExampleSynthesizer` with `GuidanceAction.GENERATE_SIMILAR`,
   - `optimize_with_guidance(grow_dataset=..., weak_examples=...)`,
   - prompt rewrite,
   - train skill,
   - fix the agent code.
6. Execute the approved action locally. For generated or changed examples, mark
   them for human label review before they can support a holdout claim.
7. Loop back to `traigent-run-plan` for a fresh service plan. Do not launch a new
   optimization run from this skill without the run-plan confirmation and mock
   dry-run flow.

## Local Report

Return a compact local report to the user:

- Run id and portal link.
- Server source used for flagged ids.
- Number of server-flagged ids and number matched locally.
- Coarse categories returned by the server.
- Local failure-pattern classifications with ids, not raw private content unless
  the user approves showing it.
- The single approved action taken.
- Files changed or examples generated.
- Any egress approval or denial.
- Next `traigent-run-plan` context.

## Privacy And Egress

The local content map can contain proprietary examples. Store it in the project
workspace or another user-approved local path, avoid committing it by default,
and delete temporary maps when the user asks. Share only safe ids and aggregate
counts with Traigent unless the user explicitly approves sending example text.

## See Also

`traigent-next-run` - fetch server recommendations.
`traigent-run-plan` - fetch and confirm the next service plan.
`traigent-curate-dataset` - exact synthesis and guided-optimization call patterns.
`traigent-iterate` - local result inspection when the user requests it.

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
