---
name: traigent-setup-audit
description: "Point Traigent at an existing agent project and get a five-minute, free, local audit of what is weak before spending anything. Use when asked to audit my agent project, check if I am ready to optimize, review my eval setup, tell me what is wrong with my dataset or scorer, find which tunable knobs are actually used, check whether my scorer is repeatable, or when a user has an agent and does not know where to start with Traigent. Reads the code, runs only the user's own deterministic scorer, makes no model calls and no Traigent calls, then names what code alone could not settle and which skill settles it."
license: Apache-2.0
metadata:
  traigent-audience: sdk-user
  traigent-topic: agent-optimization
  traigent-stage: front-door
  traigent-maturity: experimental
  author: Nimrod
  version: "0.1.0"
---

# Traigent Setup Audit

## When to Use

Requires `traigent>=0.27.0` for the two companion SDK commands named at the end of
this file. The audit script itself is standard library only and runs with no SDK
installed and no key configured.

Use this skill when a user has an agent project and one of these is true:

- "audit my agent project" / "is this ready to optimize?"
- "what is wrong with my evaluation dataset?"
- "is my scorer any good?"
- "which of my tunable knobs actually do anything?"
- they have Traigent installed, have not run anything, and do not know where to start.

Use it **first**, before `traigent-optimize-run`, `traigent-boost-agent` or a first
paid run. It is a read-only front door: it hands over to the other skills, and
reimplements none of them.

Do not use it to run an optimization, to size a run, or to reach a Traigent
service. This tier calls nothing.

## What it does, and what it costs

Everything here is static inspection of the project's own files, plus one
sandboxed call of the user's own deterministic scorer. Nothing leaves the
machine and nothing is charged.

The zero-network property is enforced, not asserted. Before any project file is
read, the audit process replaces the socket entry points with a refusal, then
proves the refusal fires and reports the result as `network_guard: active` in its
output. Every subprocess it starts — the scorer probe and the SDK-version read —
installs the same refusal as its first statement. A scorer that reaches for a
socket is stopped and reported as stopped, rather than silently succeeding.

## Run it

Resolve `<skill-dir>` to the directory holding this `SKILL.md`; plugin and
flat-install locations differ. Any Python 3.11+ interpreter works — the script
imports nothing outside the standard library, and in particular never imports
`traigent`.

```bash
python3 <skill-dir>/scripts/audit_project.py --root /path/to/project
```

Useful options:

```bash
python3 <skill-dir>/scripts/audit_project.py \
  --root /path/to/project \
  --json /tmp/traigent-setup-audit.json \
  --dataset /path/to/eval.jsonl \
  --scorer evaluators/exact.py:score \
  --repeats 5
```

- `--json` writes the same report as machine-readable JSON.
- `--dataset` audits one file instead of searching the tree.
- `--scorer FILE.py:FUNCTION` picks which scorer to probe. Without it the audit
  probes a scorer only when exactly one deterministic candidate was found.
- `--repeats` is how many times the same pair is re-scored (default 5).

Exit code is `0` whenever the audit ran, whatever it found, and `2` on a usage
error. A finding is not a failure.

## What it checks

| Area | What is read | What is reported |
|---|---|---|
| Agent | `@traigent.optimize` decorators, parsed with `ast` | entry points with `file:line`; each declared knob marked read, never read, or possibly read through a mapping |
| Dataset | JSONL / JSON arrays / CSV whose rows carry an input-like key | row count against the `traigent-dataset-curate` minimums; rows with no gold key; exact and near-duplicate inputs; whether a holdout slice exists, how large it is, and whether it overlaps another slice; label balance where the gold values are few and repeated |
| Scorer | functions named `score*`/`evaluate*`/`grade*`/`metric*`, or taking `expected` second | classification (deterministic / LLM judge / code-executing / hybrid); for a deterministic one, repeat-scoring plus a known-good, partial and known-bad probe |
| Setup | the project interpreter, the environment, `.env*` files, `git check-ignore` | installed SDK version; which key **names** are set; whether `.env` is git-ignored; which model ids the configuration space declares |

Row minimums come from `traigent-dataset-curate`: 10-20 for a smoke check, 30-100
for a first tuning slice, 30+ for a holdout slice, 100+ for a high-variance task.

An LLM-judge or code-executing scorer is **never run**. The audit says which one
it found, why it did not run it, and routes it to `traigent-eval-audit`.

The key check reads names only. No key value is read, printed or written, in the
card or in the JSON.

## Report the findings as evidence

The script already writes the card. When relaying it:

- Quote the counts and the `file:line` the script produced. "`temperature` is
  declared at `agent.py:9` and the decorated body never reads it" is a finding;
  "your config space has problems" is not.
- For anything not present, say what was searched for and where: "searched for
  `@traigent.optimize` in 41 Python files, found none". Never "you don't have a
  decorated function" — the user may have one the search did not reach.
- Recommend exactly **one** next step, with the reason in one sentence.
- Stopping after this audit is always a valid outcome. Say so.
- Never promise an improvement. This audit measures nothing about outcome.

## What code alone could not tell you

Each gap below is real, and each one needs a Traigent service call — which sends
data off the machine and can cost money. **None of them runs in this tier.** The
approval-gated second tier of this skill is where they will be offered, each
behind an explicit approval that names what runs, what leaves the machine, the
spend cap and the stop rule.

| Question the code cannot answer | What settles it | Skill to hand over to |
|---|---|---|
| Does the scorer agree with a human on real model output? | Traigent's evaluator-quality service, computed from a completed run against an independent correctness signal | `traigent-eval-audit` |
| Which individual rows are mislabelled, redundant or too hard? | Traigent's per-example scoring and dataset-quality services, computed from a completed run | `traigent-dataset-curate` |
| Does tuning move the score at all, and which knob moves it? | a small bounded optimization run, then a knob ranking over its trials | `traigent-optimize-run`, then `traigent-analyze-variable-importance` |
| What should I do next, given my own numbers? | Traigent's planning service before a run, and its decision brief after one | `traigent-analyze-guidance` |

Most of those need a **completed run** first. Say that plainly rather than
offering a check that cannot execute yet, and offer the smallest run that
produces one — or hand over to `traigent-optimize-run`.

Quote the Tier 1 finding that motivates each offer, in the user's own numbers.
"8 rows, under the 30-row tuning minimum; per-example scoring would say which of
the 8 to fix first" is motivation. A generic pitch is not.

## What this audit does not establish

- **Repeatability is not correctness.** A scorer that returns the same wrong
  number every time passes the probe. Agreement with a human is a separate
  question, and the free tier cannot answer it.
- **No lift is promised.** Nothing here says optimization will improve the agent.
  A flat or negative result is a real outcome and gets reported as one.
- **Knob wiring is detected statically.** A knob read through a mapping the
  parser cannot follow is reported as *possibly read*, never as unread.
- **Model ids are collected, not validated.** Checking an id against a provider
  is a network call, which this tier does not make.
- **Only Python is inventoried in this version.** A JavaScript or TypeScript
  project is not searched for entry points or scorers; see `traigent-js`.
- **A green audit is not a green run.** It means nothing obvious is in the way.

## Two SDK commands worth knowing, and why they are not part of the audit

Both exist in `traigent>=0.27.0`. The audit does **not** shell out to either, so
that its zero-network property stays provable rather than inherited.

- `traigent check my_module.py --dry-run` discovers `@traigent.optimize`-decorated
  functions by **importing** the module, which executes it. Without `--dry-run` it
  goes further and runs a real optimization validation, which makes model calls.
  Offer it as a companion once the user is ready to execute their own code; it is
  never a prerequisite for this audit, which parses the same file instead.
- `traigent models --check MODEL_ID` validates a model id against a **provider's**
  known model surface, not against a Traigent backend. For Anthropic it answers
  from a shipped snapshot and a pattern, with no network at all; for OpenAI,
  Mistral and Nous it asks the provider SDK to list models, and for Azure and
  Bedrock it makes an HTTP or AWS call. Because that is provider-dependent egress
  needing a provider key, it is out of this tier. It is the first, zero-cost item
  of the approval-gated tier.

## Safety

- Tier 1 contacts no provider and no Traigent service. The socket refusal is
  installed before any project file is read, and re-checked rather than assumed.
- User code runs only in the probe subprocess, only for a scorer classified
  deterministic, under a 30-second timeout. A judge or code-executing scorer is
  disclosed and routed, never sandboxed here.
- A key value is never read, shown or stored — only whether a known key **name**
  is set, and in which file it is declared.
- Anything in the second tier — every paid call and every byte that leaves the
  machine — waits for an explicit approval. Silence is not approval.

## See Also

- `traigent-setup-quickstart` — install the SDK and set a key.
- `traigent-setup-decorator` — wire a first `@traigent.optimize` function.
- `traigent-dataset-curate` — build, split and grow the evaluation dataset.
- `traigent-eval-build` — write or wire a scorer.
- `traigent-eval-audit` — assess an evaluator or LLM judge.
- `traigent-optimize-run` — run the first bounded optimization.
- `traigent-analyze-guidance` — ask the Traigent service what to do next.
- `traigent-boost-agent` — the full lifecycle, once this audit is clear.

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
