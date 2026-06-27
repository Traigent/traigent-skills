# Traigent SDK Skills

User-facing [Agent Skills](https://agentskills.io/) for the **Traigent SDKs** — zero-code LLM optimization using the Python decorator flow or the native JavaScript/TypeScript SDK. Wrap a Python function with `@traigent.optimize()` or a JS/TS function with `optimize(spec)(agentFn)`, declare a configuration space, and let Traigent search for the best model / prompt / parameter combination against your evaluation dataset.

These skills work across **all major AI coding agents**: Claude Code, Cursor, GitHub Copilot, Gemini CLI, OpenAI Codex, Windsurf, Junie, and [30+ more](https://skills.sh/).

> Looking for internal dev/CI/design skills (code review, PR automation, security forensics, UI/UX)? Those live in the internal [`Traigent/agents-skills`](https://github.com/Traigent/agents-skills) repo. **This repo holds only the user-facing SDK skills.**

## Interaction policy

Every skill carries a shared **Traigent Interaction Policy** — a managed block that instructs the coding agent to track the user's expertise (`se` / `ds`) and autonomy preference (`delegate` / `guided` / `inspect`) and adapt verbosity, terminology, and how much it stops to ask accordingly. The policy also enforces that the agent always recommends the next Traigent skill or action to take at the end of each response. The canonical text lives in [`docs/shared/interaction-policy.v1.md`](docs/shared/interaction-policy.v1.md) and is propagated to all skills by `python tools/contract/sync_interaction_policy.py`.

## Skills

These skills guide your agent through the full Traigent optimization lifecycle, in roughly the order you'd use them:

| Skill | Description |
| ----- | ----------- |
| [traigent-quickstart](skills/traigent-quickstart/) | Install and set up the Traigent SDK — `pip install`, environment variables (`TRAIGENT_API_KEY`), mock mode, evaluation dataset creation in JSONL, and a first `@traigent.optimize` decorated function. |
| [traigent-curate-dataset](skills/traigent-curate-dataset/) | Build, split, grow, and score Traigent evaluation datasets — assess existing examples, JSONL format and holdout discipline, client-side synthesis with `ExampleSynthesizer`/`optimize_with_guidance(grow_dataset=…)`, backend generation endpoints, post-run example scoring via `ExampleInsightsClient`, and the improve loop. |
| [traigent-choose-metric](skills/traigent-choose-metric/) | Choose what to measure before optimizing — the 6-question metric interview, the measure-type vocabulary (accuracy, quality, latency, safety, efficiency, reliability, sanity_check), built-in objective names, multi-objective accuracy+cost patterns, and when a safety property belongs in a gate instead. |
| [traigent-build-evaluator](skills/traigent-build-evaluator/) | Wire or implement an evaluator — the 5-tier wire-first ladder (`eval_dataset` → `scoring_function` → `metric_functions` → `custom_evaluator` → `BaseEvaluator`), the `ExampleResult` contract, and deterministic / LLM-judge / statistical / hybrid templates with fail-closed parse handling. |
| [traigent-evaluator-audit](skills/traigent-evaluator-audit/) | Audit evaluator and LLM-judge reliability — gold-slice agreement, repetition stability, bias probes (position, length, self-preference), parse-failure policy, threshold calibration, and when to demote a judge to a hybrid gate. |
| [traigent](skills/traigent/) | The end-to-end driver with a lifecycle table: dataset → metric → evaluator → optimize → iterate → gate, while keeping **dry-run validation (mock mode)** before any paid real execution. Start here when optimizing a function for the first time. |
| [traigent-js](skills/traigent-js/) | Set up and run native JavaScript/TypeScript optimization with `@traigent/sdk` — `optimize(spec)(agentFn)`, `param.*` search spaces, evaluation blocks, trial context, budgets, injection modes, and hybrid config-space authoring. |
| [traigent-configuration-space](skills/traigent-configuration-space/) | Define which parameters the optimizer can tune and how — `Range`, `IntRange`, `Choices`, `LogRange` types, factory presets like `Range.temperature()` and `Choices.model()`, inter-parameter constraints, and `ConfigSpace` bundling. |
| [traigent-decorator-setup](skills/traigent-decorator-setup/) | Configure `@traigent.optimize()` beyond the basics — `EvaluationOptions` (datasets, custom evaluators, scoring), `InjectionOptions` (how optimized configs reach your function), `ExecutionOptions` (sync/async, timeouts, local-only), and multi-objective optimization. |
| [traigent-run-optimization](skills/traigent-run-optimization/) | Run optimization end-to-end — async/sync execution via `func.optimize()` and `optimize_sync()`, algorithm selection (grid, random, bayesian, optuna), trial limits, cost budgets, `ParallelConfig` for concurrent trials, and `CostLimitExceeded` handling. |
| [traigent-analyze-results](skills/traigent-analyze-results/) | Inspect `OptimizationResult` objects — best config and score, individual trial comparison, stop-reason interpretation, cost/token usage tracking, and `apply_best_config()` for production deployment. |
| [traigent-iterate](skills/traigent-iterate/) | Decide the most promising next step after a run — read result, importance, and example-side evidence first, then a symptom→action table for flat, noisy, dominated, tied, budget-bound, or weak-example outcomes; one iteration = one hypothesis. |
| [traigent-ci-safety-gate](skills/traigent-ci-safety-gate/) | Gate an optimized agent — in-run `safety_constraints`, candidate-vs-incumbent `PromotionGate`, TVL spec validation, and GitHub Actions checks for safety (holdout regression) and efficiency (cost/latency budgets). |
| [traigent-integrations](skills/traigent-integrations/) | Integrate Traigent with AI frameworks — LangChain, LiteLLM, and DSPy adapter patterns, multi-provider model testing (OpenAI + Anthropic + Google), `auto_override_frameworks`, and observability via MLflow and Weights & Biases. |
| [traigent-debugging](skills/traigent-debugging/) | Troubleshoot optimization failures — mock mode for CI/CD without API keys, `TRAIGENT_LOG_LEVEL=DEBUG` logging, error-class reference (`CostLimitExceeded`, `ConfigurationError`, `OptimizationStateError`), and missing-dependency diagnosis. |
| [traigent-structural-spine](skills/traigent-structural-spine/) | Author a *structural* configuration spine (not just model + one prompt string) when turning an `@traigent.optimize` evaluator into an optimizer — structural knob taxonomy for text2SQL (schema context, generation path, few-shot, candidate voting, repair) and RAG / multi-hop QA (retriever, retrieval-k, query decomposition, context order, answer path, self-consistency), the before/after decorator diff, and a local-optimizer operational checklist. |
| [traigent-composite-knobs](skills/traigent-composite-knobs/) | Declare and run Traigent composite knobs — cascades, routers, ensembles, self-consistency, best-of-n, self-refine, self-debug, ReAct tool loops, verification gates, mixture-of-experts, and fallback patterns, with StageRunner wiring, telemetry-to-measures merging, and honest calibration-backed claim scope. |
| [traigent-boost-agent](skills/traigent-boost-agent/) | 12-step lifecycle orchestrator for adding Traigent to an existing client agent codebase end-to-end — analyze code, curate the evaluation dataset, choose metrics, wire or audit evaluators, select TVARs and composites, instrument minimally, validate in mock mode, run approved real optimization, inspect configuration and example insights, iterate, and recommend safety/CI gates. |
| [show-significant-tuned-variables](skills/show-significant-tuned-variables/) | Rank which tuned variables actually drove observed optimization gains — per-value objective spread, variance-decomposition share, bootstrap confidence intervals, honest `significant` vs `directional` labels, and a one-glance SVG summary card. |

## Install

### Via `npx skills` (recommended)

```bash
# List available skills in this repo
npx skills add Traigent/traigent-skills --list

# Install a specific skill
npx skills add Traigent/traigent-skills --skill traigent-quickstart

# Install several
npx skills add Traigent/traigent-skills \
  --skill traigent-quickstart --skill traigent-js --skill traigent-run-optimization

# Install all of them
npx skills add Traigent/traigent-skills --skill '*'

# Update installed skills later
npx skills update
```

`npx skills` copies each skill into the correct location for your agent automatically, and keeps it in sync with this repo.

### Manual (any agent)

Clone this repo and copy the skills you want into the folder your agent scans.

```bash
git clone https://github.com/Traigent/traigent-skills.git

# Cross-agent standard path
cp -r traigent-skills/skills/traigent-quickstart .agents/skills/

# Claude Code specific path (auto-discovered on startup)
cp -r traigent-skills/skills/* ~/.claude/skills/
```

**Codex (OpenAI) on VSCode** does not auto-discover skill folders — inline the instructions into your project's `AGENTS.md`:

```bash
for skill in traigent-skills/skills/*/SKILL.md; do
  echo -e "\n---\n" >> AGENTS.md
  cat "$skill" >> AGENTS.md
done
```

## How skills work

Skills follow the [Agent Skills open standard](https://agentskills.io/specification). Your AI coding agent loads skill names and descriptions at startup (~100 tokens each). When a skill is relevant to your task, the agent loads the full instructions automatically using **progressive disclosure**:

- **`SKILL.md`** — core instructions and examples (< 5000 tokens), loaded when the skill activates.
- **`references/`** — detailed API docs loaded on demand when the skill needs them.

```text
skills/<skill-name>/
  SKILL.md       # YAML frontmatter (name + description) + Markdown instructions
  references/    # deeper API docs, loaded on demand
```

These skills are **pure Markdown** — no executable scripts, no network calls, no credential reads.

## Requirements

**To use the skills themselves: nothing.** They're plain Markdown instructions your AI coding agent reads — no runtime, no scripts, nothing to install.

The skills *teach your agent to drive the Traigent SDKs*, so to actually run an optimization you'll need the relevant SDK in your own project:

- Python 3.11–3.13
- Traigent SDK — `pip install traigent`
- Node.js 18, 20, or 22
- Traigent JS SDK — not published on public npm yet; use the source/link flow in
  `skills/traigent-js` until Traigent/traigent-js#165 lands.

## Maintenance

[`SYNC_MAP.md`](SYNC_MAP.md) maps each skill to the Traigent SDK source files it documents. When the SDK changes, review the corresponding skills for accuracy.

## Skill governance

Skill updates use protected regions, per-skill provenance, and versioned, score-gated changes. `SKILL.md` frontmatter is implicitly protected because YAML must remain first; invariant claim-scope, caveat, and safety constraints are wrapped with `<!-- PROTECTED -->` markers, and each skill has a `provenance.json` document hash.

Optimizer-proposed edits are accepted only through reviewed PRs that pass a strictly-greater held-out baseline. Marker and provenance adoption keeps existing `metadata.version: "1.0"` values; the version bump discipline starts with the next instructional content change. See [skill-evals/README.md](skill-evals/README.md).

## License

Apache-2.0 — see [LICENSE](LICENSE). Same as the Traigent SDK.
