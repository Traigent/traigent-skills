---
name: traigent-build-agent
description: Build a new customer-owned AI agent from a task brief, using eight stages to deliver its code, evaluation dataset, evaluator, and measured handoff. Use boost-agent for an existing working agent that only needs optimization.
license: Apache-2.0
metadata:
  traigent-audience: sdk-user
  traigent-topic: agent-optimization
  traigent-stage: front-door
  traigent-maturity: experimental
  author: Traigent
  version: "1.0.0"
---

# Build an agent from ground zero

## First message

Open with exactly this message, then inspect the project and existing answers:

> We will build your agent in eight stages: Contract, Authority, Baseline, Dataset, Evaluator, Challenge, Improve, and Handoff. I will reuse what you already have, show measured progress, and ask before paid calls. The result is your agent, evaluation data, evaluator, and a record of what was verified.

Use the customer's current coding assistant and project. Connected product reads
need `TRAIGENT_API_KEY` and `TRAIGENT_PROJECT_ID`; provider access, if a paid run
requires it, remains the customer's existing local configuration. Never request
secret values in chat or put them in arguments, reports, or commits. This workflow
requires no Docker, AWS account, gateway, or research checkout. It is an
instructional skill, not a runtime consent enforcer or a hosted build service.
Requires `traigent>=0.24.0` for connected decision reads.

## Evidence and progress

Maintain a local build record in the project's existing reports location. Record
stage, source revision, artifact paths, exact check command, complete output,
exit status, and limitations. Reuse existing valid artifacts; do not invent data,
results, run IDs, elapsed time, or tool-call counts. Show stage progress from this
record and actual timestamps. Label unavailable measurements `not measured`.

At every stage, consult the latest applicable server decision brief. Before any
connected run exists, record `not_available_before_run`; this is not a failed run
or a reason to fabricate an ID. Local preparation may continue. Once a run is
claimed, fetch fresh evidence using `analytics_get_run_decision_brief` with the
explicit project and run IDs, or the read-only helper shipped here:

```bash
python <installed-skill>/scripts/read_decision_brief.py --run-id <recorded-run-id>
```

The helper uses the SDK's credential and project-scoped read path, verifies the
returned IDs and intent, and prints the complete brief unchanged as JSON. It has
no `--offline`, cached-payload, or fallback mode. HTTP failures, missing runs,
unauthorized runs, malformed evidence, and mismatched IDs refuse verification.
Do not advance a stage claiming a verified run when that read fails; report the
actual failure and continue only independent preparation. An operator's pasted
or local receipt alone is not backend verification.

Present `headline`, `confidence`, `recommended_action`, `evidence`, and `warnings`
verbatim. Never replace low confidence with local confidence, manufacture a
promotion verdict, or describe an unfinished run as completed. A valid backend
record proves the run exists in scope; it does not prove that the agent passes a
customer acceptance test. Follow the returned action through the existing
analyze-guidance workflow. A brief is advice, never permission for paid calls,
production writes, or deployment.

## Eight stages

| Stage | Work and evidence needed to advance |
|---|---|
| Contract | Record the task, input/output contract, supported and refused actions, success measure, and operating constraints. Resolve material ambiguity with the customer; infer routine implementation choices from the project. |
| Authority | Record permitted data, tools, credentials by name, network destinations, and side effects. Separate tuning data from holdout data before development; record who owns the reference labels and acceptance standard. Unsettled authority blocks only dependent actions. |
| Baseline | Implement the smallest functioning agent against the contract. Run local deterministic checks and a disclosed mock smoke test first. Record failures honestly; mock scores are not measured agent quality. |
| Dataset | Reuse or curate representative tune and held-out rows with stable IDs and provenance. Document sensitive-data handling and label uncertainty. Never silently fill missing labels with random or default answers. |
| Evaluator | Wire the customer's intended measure, validate schema, calibrate on good/equivalent/partial/bad cases, and record observed failures. Keep evaluator authorship separate from independent acceptance authority. |
| Challenge | Test relevant failure cases, adversarial inputs, and held-out data without tuning on the holdout. Preserve failing cases. A self-authored reference may support development calibration, not independent qualification. |
| Improve | Propose one measured change from the brief and local evidence. Use an isolated candidate process, bounded search, and explicit approval for paid calls. Record the backend run and verify it before claiming success. |
| Handoff | Deliver agent source, dataset/split provenance, evaluator/calibration, configuration, reproducible checks, run links, spend where measured, and known failures. State separately what works locally, what the backend verified, and what independent acceptance did not establish. |

For SDK wiring, use setup-quickstart and setup-decorator; for dataset and evaluator
work, use dataset-curate, eval-build, and eval-audit; for connected optimization,
use optimize-run and analyze-guidance; for promotion, use ci-safety-gate. If those
skills are absent, read their maintained instructions from this repository before
using that operation. Do not guess APIs or install unrelated infrastructure.

## Paid calls and execution evaluators

Before any provider call, show an approval card with the exact candidate/check,
provider and model, data destination, trial and spend caps, timeout/stop rule,
expected evidence, and any unverified evaluator behavior. Explain what will run
and why. Require an explicit yes for that scope; earlier PR approval, a brief,
mock success, or silence is not consent. Reuse a still-valid approval for its exact
scope and bound; ask again when the operation exceeds it. Approval records in the
build log are instructions to the coding assistant, not a security boundary.
Do not claim that this skill intercepts or blocks calls made outside its workflow.

SQL output is a supported task; executing generated SQL is a separate operation.
The guided first-run's run-safety reference owns its evaluator boundary: it does
not initiate calibration of an executing evaluator against the customer's original
engine. Preserve that evaluator and follow its documented contained-copy or
customer-supplied-result route with the required disclosure. Do not rewrite it to
comparison scoring to hide that boundary. A timeout, virtual environment, or mock
flag is not containment. A separate customer-authorized execution design must
establish read-only data scope, isolation, resource limits, and cleanup before this
skill initiates calibration outside that guide. Otherwise record `not assessed`
and continue independent work; never claim execution accuracy was checked.

A passing development scorecard or SDK gate does not establish independent
qualification. That requires separately owned references, frozen acceptance
criteria, hidden holdout handling, and real measurements. List those missing items
in the handoff; do not manufacture an independent assessor or a success screenshot.

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
- Recommend the next skill only after a result-bearing step (a run finishes, an analysis
  completes, a configuration validates) or an explicit decision point. Omit recommendations
  during setup or mid-walkthrough. Cap at 3 recommendations per response, each on its own line
  with a one-line eligibility reason (e.g., "traigent-analyze-results — ✓ run succeeded" or
  "traigent-optimize-run — ✓ config validated").
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
