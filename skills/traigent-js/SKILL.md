---
name: traigent-js
description: "Set up and run native JavaScript/TypeScript optimization with @traigent/sdk. Use when a user asks to optimize a JS/TS agent function, use optimize(spec)(agentFn), configure param.* search spaces, define evaluation.data/loadData metrics, use getTrialParam/getTrialConfig, or author backend-routed config-space specs for Traigent-compatible services."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.0.4"
---

# Traigent JS/TS SDK

Use this skill for `@traigent/sdk`, the native JavaScript/TypeScript SDK. Do not apply the Python `@traigent.optimize` decorator workflow to JS projects.

## Installation

`@traigent/sdk` is **not published to the public npm registry yet** — `npm install @traigent/sdk` returns a **404**. Until npm publishing is enabled, build it from source (per the [repo README](https://github.com/Traigent/traigent-js)):

```bash
git clone https://github.com/Traigent/traigent-js.git
cd traigent-js
npm install
npm run build
```

Then consume the local build from your project — run `npm link` in the cloned repo and `npm link @traigent/sdk` in your project, or add it as a path/`file:` dependency. Supported Node: 18, 20, 22. (Public npm publishing is tracked in Traigent/traigent-js#165.)

## Core Pattern

The primary JS flow wraps a plain agent function:

```ts
import { getTrialParam, optimize, param } from '@traigent/sdk';

const answerQuestion = optimize({
  configurationSpace: {
    model: param.enum(['cheap', 'accurate']),
    temperature: param.float({ min: 0, max: 0.5, step: 0.5, scale: 'linear' }),
  },
  budget: {
    maxCostUsd: 2,
  },
  execution: {
    maxTotalExamples: 100,
    exampleConcurrency: 4,
    repsPerTrial: 3,
    repsAggregation: 'median',
  },
  evaluation: {
    data: [
      { input: 'What is 2+2?', output: '4' },
      { input: 'What is the capital of France?', output: 'Paris' },
    ],
    metrics: {
      accuracy: (output, expectedOutput) => output === expectedOutput,
      cost: (_output, _expectedOutput, _runtimeMetrics, row) =>
        row.input.includes('capital') ? 0.2 : 0.1,
    },
  },
})(async (question: string) => {
  const model = String(getTrialParam('model', 'cheap'));
  const temperature = Number(getTrialParam('temperature', 0));
  return callLlm({ model, temperature, question });
});

const result = await answerQuestion.optimize({
  algorithm: 'grid',
  maxTrials: 10,
  timeoutMs: 5_000,
});

console.log(result.bestConfig);
console.log(result.bestMetrics);
answerQuestion.applyBestConfig(result);
```

## Workflow

1. Install `@traigent/sdk` — build from source, see **Installation** above (not on public npm yet).
2. Define `configurationSpace` with `param.enum`, `param.float`, `param.int`, or another exported parameter helper.
3. Add `evaluation.data` or `evaluation.loadData`, plus metrics that score outputs. Default to at least one metric named `accuracy`; if accuracy doesn't apply, name the primary quality KPI after the product concept and note why accuracy was skipped.
4. Set `budget.maxCostUsd`, `timeoutMs`, and trial/example limits before running.
5. Run `await wrapped.optimize(...)`.
6. Inspect `result.bestConfig`, `result.bestMetrics`, trial details, stop reasons, and cost metrics.
7. Call `wrapped.applyBestConfig(result)` only after reviewing the winning config.

## Runtime Rules

- Native/local algorithms are `grid` and `random`.
- Smart strategy names accepted by the JS SDK's algorithm contract are the `bayesian`/`optuna`/`tpe` family plus `cmaes`/`nsga2` variants (`SMART_OPTIMIZATION_ALGORITHMS` in `src/optimization/algorithm-contract.ts`). They are backend-routed surfaces, not native local search implementations — this skill does not claim they currently execute. **`hyperband` is not an accepted JS algorithm name, and `frontier_scout` is not an algorithm at all** — it is TVL selection-policy vocabulary (see below).
- **Backend availability (verified server-side 2026-07-02):** the backend's **classic session-create path** — the one the Python decorator uses — executes only `grid`/`random` and rejects other algorithm names. A **separate typed/interactive backend session API** does support `optimization_strategy.algorithm="optuna"` with TPE/random/CMA-ES samplers. Whether the JS SDK's smart strategies route to that typed path has **not been verified** — confirm live behavior against your backend before promising a smart strategy runs; do not present them as verified-working values.
- In TVL promotion/selection policy, `pareto_optimal` is accepted as a compatibility alias for `frontier_scout` — selection-policy vocabulary, not an `algorithm` value.
- `evaluation.data` or `evaluation.loadData` is required for high-level native optimization.
<!-- PROTECTED -->
- `budget.maxCostUsd` is enforced from numeric `metrics.total_cost` or `metrics.cost`; provider billing remains the user's responsibility.
- The JS SDK has no pricing tables or pricing env vars. Cost exists only when the trial returns numeric `metrics.total_cost`, `metrics.cost`, or `metrics.input_cost` plus `metrics.output_cost`.
- Before any full run, verify with a tiny real optimization that cost and your other KPIs are actually tracked: trial metrics must include numeric cost and populated objective metrics, with an `accuracy` metric by default unless accuracy does not apply. If not, return the cost metrics directly before scaling up. The probe is itself a paid run — the same dry-run-first / explicit-user-approval gate applies to it.
<!-- /PROTECTED -->
- Trial context is available during wrapped execution. Use `getTrialParam`, `getTrialConfig`, `TrialContext.run`, `isInTrial`, and `wrapCallback` rather than module-level globals.
- JS supports `context`, `parameter`, and `seamless` injection modes. Use `context` unless the host app naturally accepts a config parameter or intentionally opts into seamless framework/rewrite support.

## Offline / Zero-Egress

Set `offline: true` in the optimize spec when the run must avoid Traigent-backend
egress. `TRAIGENT_OFFLINE_MODE` is also recognized. Mode `"local"` is the
recommended, non-deprecated canonical mode for local/offline optimization;
legacy aliases such as `"native"` are deprecated and map to it.

In offline mode, backend HTTP is refused by the SDK's offline guard and only
local algorithms (`grid` and `random`) run. Do not expect portal tracking or
backend-routed strategies in this mode.

Honest boundary: zero-egress means no Traigent-backend egress. Calls to the
user's own LLM provider still happen if their agent makes them.

## Common Fixes

| Problem | Fix |
|---|---|
| Python decorator suggested in JS | Use `optimize(spec)(agentFn)` from `@traigent/sdk`. |
| No evaluation data | Add `evaluation.data` or `evaluation.loadData`. |
| Context missing in delayed callbacks | Use `wrapCallback` or run host-managed execution inside `TrialContext.run(...)`. |
| Smart strategy expected to run locally | Use native `grid`/`random`. Backend routing helps only if the request reaches the backend's typed interactive session API — the classic session path serves only `grid`/`random`, and JS routing to the typed path is unverified (see Runtime Rules). |
| Cost budget not enforced | Return numeric `metrics.total_cost`, `metrics.cost`, or `metrics.input_cost` plus `metrics.output_cost` for every trial. |
| Metric cannot be aggregated | Return numeric or boolean metrics with stable names. |

## Verification

Use the repo's local commands when available:

```bash
npm test
npm run typecheck
```

If the project uses examples, prefer a small native optimization smoke with `algorithm: 'grid'`, low `maxTrials`, and a tiny in-memory evaluation dataset before any backend-routed or full paid run. Verify trial metrics include numeric cost and populated objective metrics before increasing the run size.

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
