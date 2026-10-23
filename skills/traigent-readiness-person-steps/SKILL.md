---
name: traigent-readiness-person-steps
description: "Hand a person-only Traigent readiness step to a human, wait, then verify. Use when an agent's readiness or next step is owned by a PERSON (actor PERSON: assign the owner, declare deployment stage, criticality or accuracy requirement, sign off the evaluation set or evaluator, grant a reviewer), when an API key is refused for a governance act, or when asked to make an agent production-ready and a step needs a human. Reads next-step and readiness, builds portal links, checks the reviewer grant first, posts one request, waits, then re-reads readiness and reports what changed."
license: Apache-2.0
metadata:
  traigent-audience: sdk-user
  traigent-topic: agent-optimization
  traigent-stage: gate-debug
  traigent-maturity: experimental
  author: Traigent
  version: "1.0.0"
---

# Readiness: hand a person-only step to a person

## When to Use

Use this skill when a Traigent agent's **next step** or an `also_needed` entry has
`actor == "PERSON"`, or when a write is refused because it is a governance act that only a
signed-in person may perform. You do not do the act. You give the person a link, wait,
and then check the result yourself.

Typical triggers:

- "make this agent production-ready" and readiness still lists declarations nobody has made
- the next step is `ASSIGN_AGENT_OWNER`, or `also_needed` carries `OWNER_NOT_ASSIGNED`,
  `DEPLOYMENT_STAGE_NOT_DECLARED`, `CRITICALITY_NOT_DECLARED` or `ACCURACY_REQUIREMENT_NOT_DECLARED`
- the evaluation dataset or evaluator needs a reviewer's sign-off
- a write with an API key returned 403 `authorization_denied` for a stage, criticality, owner,
  sign-off or reviewer-grant act

This skill is for **customer-side coding agents**. It sends nothing to the Traigent Director.

<!-- PROTECTED -->
Never perform a person-only act with an API key, never look for a way around a refusal, and
never mark a person step done because the person said it was. Re-read readiness and report what
the API shows. A 403 on one of these acts is the intended answer, not an error to route around.
<!-- /PROTECTED -->

## Rules that always apply

- **People commit, agents prepare.** Owner, deployment stage, criticality, accuracy-requirement
  confirmation, dataset/evaluator sign-off and reviewer grants are accountability acts. Hand them over.
  Do not try other credentials, other endpoints, a different principal or a capability toggle.
- **Never trust the click.** Done means the next read of readiness shows it, not that the person replied "done".
- **Post ONE request and wait.** Do not re-post, nag or poll in a loop. After the person answers, read once.
- **Keep customer content out of the handoff's machine channels.** Customer-chosen identifiers (agent
  names, ids, dataset or example ids, labels) are content. Never put them into a Director payload, a
  run name, telemetry or a log. Build the link on this side and show it to the person only.
- **Observability is not privacy-preserving.** Do not route anything that must stay on the customer side
  through observability or tracing to "tell" the person or to record the handoff.

## Step 1: read the next step and readiness

Read the two endpoints for the agent. Prefer the SDK; use documented REST only where the SDK has no call.

- `GET /api/v1beta/projects/{project}/agent-readiness/{agent_id}/next-step`: the ONE next step
  (`state`, `step{code, actor, required{role, human_session_only, capability}, destination}`, `also_needed[]` of `{code, actor}`, `basis`).
- `GET /api/v1beta/projects/{project}/agent-readiness/{agent_id}`: the readiness verdict per pillar.

The SDK's `RuntimeClient(project_id).get_next_step(agent_id)` makes the first call. As of 2026-10-23
`RuntimeClient` is on the SDK development branch and **not in the 0.31.0 release**, so check
`python -c "from traigent.runtime.client import RuntimeClient"` first. If it imports, use it; if it
does not, use `requests` with the SDK's own User-Agent. Do not use `urllib`: Traigent's edge firewall
blocks its default User-Agent, and the failure looks like an authentication error.

```python
import os
import requests
from urllib.parse import quote

from traigent.cloud.user_agent import get_sdk_user_agent
from traigent.config.backend_config import BackendConfig

project = "<project id>"  # the project's id from the portal, not its display name
agent_id = "my-agent"
headers = {
    "X-API-Key": BackendConfig.get_api_key(),
    "Accept": "application/json",
    "User-Agent": get_sdk_user_agent(),
}
base = f"{BackendConfig.get_backend_url().rstrip('/')}/api/v1beta/projects/{quote(project, safe='')}"
agent = quote(agent_id, safe="/")
next_step = requests.get(f"{base}/agent-readiness/{agent}/next-step", headers=headers, timeout=30)
readiness = requests.get(f"{base}/agent-readiness/{agent}", headers=headers, timeout=30)
print(next_step.status_code, readiness.status_code)  # a 404 here is the closed "cannot see this agent" answer
```

Never print the key. A 404 means the key cannot see the agent (or it does not exist): stop and ask
the person to check project access. A 503 or `RETRY_LATER` is a retry later, not a person step.

**Treat the readiness API as the authority.** Other copies of the same advice (the Director
`also_needed`, a dashboard, an earlier turn) can disagree with it. If they do, report the disagreement
and follow the readiness read.

## Step 2: pick out the person steps

A person step is `step.actor == "PERSON"` **or** any `also_needed[]` entry with `actor == "PERSON"`.
Collect them all into one list before you contact anyone. Ignore `TRAIGENT` and `CODING_AGENT` steps
(do those yourself) and note any `step.required.capability` or `human_session_only: true`, which you
will pass on to the person as prerequisites.

Record the set of person codes you found. Step 6 compares against it.

## Step 3: build the portal link

Use the web origin, not the API origin:

- In Python: `BackendConfig.get_cloud_web_url()` (honours `TRAIGENT_WEB_URL`, then
  `TRAIGENT_PORTAL_URL`, then derives the portal host from the configured API host, then falls back to production).
- Without the SDK: the person's portal host (for example `https://portal.traigent.ai`).

**Portal URLs carry no project id today.** The portal takes the project from the project selector. Always
tell the person: "select project **<project name>** in the project selector first, then open the link."
Without that, the link can open the wrong project and the act lands on a different agent or fails.

`<agentId>` is the portal route parameter in `/agents/view/<agentId>`. Whether it is the agent id or the
agent key is unverified; if the page shows "not found", ask the person to open the agent from the agent list.

| Code | Link (after the web origin) | Who and what must be on |
|---|---|---|
| `OWNER_NOT_ASSIGNED` (also needed), `ASSIGN_AGENT_OWNER` (step) | `/agents/view/<agentId>` (owner panel); alternative `/findings` then "Assign owner" | A signed-in tenant owner or admin; team features and the agent-settings authoring capability enabled |
| `DEPLOYMENT_STAGE_NOT_DECLARED` | `/agents/view/<agentId>?declare=posture` | A signed-in tenant owner/admin or project admin; agent-settings authoring capability enabled |
| `CRITICALITY_NOT_DECLARED` | `/agents/view/<agentId>?declare=posture` (same dialog as stage) | same |
| `ACCURACY_REQUIREMENT_NOT_DECLARED` | `/findings`, the "requirement undeclared" row, then "Declare accuracy requirement" | An editor; agent-settings authoring capability and the findings features enabled. Propose the value first, see below |
| Evaluation dataset sign-off | `/agents/view/<agentId>?tab=details`, review panel, dataset subject | A signed-in person with an active reviewer grant, and a completed anchor run |
| Evaluator sign-off | `/agents/view/<agentId>?tab=details`, review panel, evaluator subject | same |
| Reviewer grant (when nobody can sign) | `/projects`, select the project, "Evaluation system reviewers" | A signed-in project admin |
| `REQUEST_ACCESS` | no portal route located | The person needs access to the agent; ask them how access is requested in their tenant |

Other person codes (for example latency target, validity decay, progression pending): read the code's
meaning from the API response, say so, and ask the person where to act. Do not invent a link.

**Accuracy requirement.** An API key may be able to write a target, but the target is a commitment
someone is accountable for. Compute and show a proposed value with its evidence (for example "baseline
0.82 on 120 holdout rows"), put it in your request, and let the person confirm it in the portal. Do not
write it for them.

If the capability or feature a link depends on is off for the person's tenant, the page may be hidden with
no message. If you can read the person's capabilities with the key (for example the auth "me" call), check
them before sending a dead link; if you cannot, say the check was not possible and list the capability
the person needs.

## Step 4: before a sign-off, check a reviewer exists

A dataset or evaluator sign-off needs a person who holds an active **evaluation-system reviewer** grant on the
project. Project admin alone is not enough. Before you hand off a sign-off, check:

```python
grants = requests.get(
    f"{base}/evaluation-system-reviewer-grants", params={"active": "true"}, headers=headers, timeout=30
)
print(grants.status_code, grants.json())
```

A viewer-level API key can list grants. If the active list is **empty**, hand off the **reviewer grant first**
(to a project admin, in the same single request) and say the sign-off comes after it. If the list is not
empty, tell the person which signing capability is needed; do not print other members' names or emails
into logs. If the call is refused, say the reviewer check could not be done and why.

## Step 5: post ONE request, then wait

Write one message to the person containing:

1. **Goal and distance:** the goal in a sentence and how many person steps there are ("2 steps need you").
2. **For each step:** what it is for in plain words, the link (web origin plus path), who can do it and
   what must be enabled, and what "done" means as something you will check ("readiness no longer lists
   `DEPLOYMENT_STAGE_NOT_DECLARED`").
3. **The project reminder:** "select project **<name>** first".
4. **How to answer:** "reply `done` when finished, `partly` with what remains, or `skip` to defer".

Then wait:

- In an agent harness with background waits or a task/approval tool, use that to resume when the person answers.
- Otherwise stop and ask the person to reply "done". Do not poll the API on a timer, and do not post again.

While you wait, continue any step that does not depend on the answer (coding-agent steps, tests). If
nothing is left, write down where you stopped and end the turn.

## Step 6: verify, never trust the click

When the person answers, re-read both endpoints (Step 1) once and compare with the codes you recorded.

Report exactly what changed, with the read as the handle:

- **Cleared:** "Gone from `also_needed` since the first read: `DEPLOYMENT_STAGE_NOT_DECLARED`,
  `CRITICALITY_NOT_DECLARED`. Next step is now `<code>` (actor `<actor>`)."
- **Still open:** name each remaining code and the likely reason, from what the response and the
  prerequisites show: the person lacked the **role** (tenant owner/admin or project admin), lacked the
  **capability** or **reviewer grant**, had the **wrong project** selected, or the capability or feature
  is **off** for the tenant. Say which one you can tell from evidence and which is a guess.
- **Changed but not as expected:** report it as found; do not call it done.

If a step stays open, you may re-post **once** with only what remains and the specific reason. If it is still open
after that, mark it deferred, tell the person what is blocked on it, and continue other work. Never switch to
an API-key write to "finish" it.

## Known gaps

- **No backend deep links yet.** The next step carries a `destination` (type and ids), not a URL, so the links
  above are built by this skill from a table. They can go stale when the portal changes routes. Re-check a link
  that lands on a not-found page before blaming the person.
- **Portal URLs have no project id.** The person must select the right project first; a link cannot select it.
- **Owner state is hidden from API keys until the pending backend change lands.** Until then a key can see
  `OWNER_NOT_ASSIGNED` as "not served" rather than assigned or unassigned, and the Director and the readiness
  API can disagree. You cannot verify the owner step with a key today; ask the person to confirm it in
  the portal and say it is unverified.
- **The posture dialog is hidden silently if the person is not a tenant owner/admin (or project admin).** There
  is no error, the dialog just does not open. Tell the person up front who can do it, and if they report
  "no dialog", suggest asking a tenant owner/admin rather than retrying.
- **A feature or capability switch can leave a person step with no surface at all.** Report it as blocked, not as a person problem.
- **The Director route is not the authority for these steps.** It is switched off by default for next steps and
  forces a wait on person steps; the readiness API is the source you act on.
- **`RuntimeClient` is not in a stable SDK release yet** (see Step 1); the REST call above is the fallback.
- Preconditions in the table (roles, capabilities) come from reading the code on 2026-10-23, not from a
  live check on your tenant. Treat them as expectations.

## Related skills

- `traigent-eval-audit` for deciding whether the evaluator is worth signing off before you ask a person.
- `traigent-ci-safety-gate` for the promotion gate once readiness is clear.

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
import asyncio
policy = None
try:
    policy = asyncio.run(client.get_interaction_policy(skill="<this skill>"))
except Exception:
    pass
# Inside an async function (an event loop is already running), use
#   policy = await client.get_interaction_policy(skill="<this skill>")
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
- When the user asks which Skills were used, answer briefly from what the session establishes: name the
  relevant Skills actually consulted, any that were unavailable, and any relevant deferred step with its
  reason. Keep installed availability, consultation and user-directed selection distinct, and never infer
  absence from non-use. Example: "Consulted quickstart and eval-build; post-run analysis is deferred
  because no optimization result exists." Do not volunteer this unasked.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
