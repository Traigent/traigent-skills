# Traigent SDK Skills

User-facing [Agent Skills](https://agentskills.io/) for the **Traigent SDKs** — zero-code LLM optimization using the Python decorator flow or the native JavaScript/TypeScript SDK. Wrap a Python function with `@traigent.optimize()` or a JS/TS function with `optimize(spec)(agentFn)`, declare a configuration space, and let Traigent search for the best model / prompt / parameter combination against your evaluation dataset.

These skills work across **all major AI coding agents**: Claude Code, Cursor, GitHub Copilot, Gemini CLI, OpenAI Codex, Windsurf, Junie, and [30+ more](https://skills.sh/).

> Looking for internal dev/CI/design skills (code review, PR automation, security forensics, UI/UX)? Those live in the internal [`Traigent/agents-skills`](https://github.com/Traigent/agents-skills) repo. **This repo holds only the user-facing SDK skills.**

## Interaction policy

Every skill carries a shared **Traigent Interaction Policy** — a managed block that instructs the coding agent to track the user's expertise (`se` / `ds`) and autonomy preference (`delegate` / `guided` / `inspect`) and adapt verbosity, terminology, and how much it stops to ask accordingly. The policy also enforces that the agent always recommends the next Traigent skill or action to take at the end of each response. The canonical text lives in [`docs/shared/interaction-policy.v1.md`](docs/shared/interaction-policy.v1.md) and is propagated to all skills by `python tools/contract/sync_interaction_policy.py`.

## Skills

These 18 skills guide your agent through the full Traigent optimization lifecycle, grouped by the stage where you'd reach for them:

| Stage | Skill | Description |
| ----- | ----- | ----------- |
| Front door | [traigent-boost-agent](skills/traigent-boost-agent/) | 12-step lifecycle orchestrator for adding Traigent to an existing client agent codebase end-to-end — analyze code, curate the evaluation dataset, choose metrics, wire or audit evaluators, select TVARs and composites, instrument minimally, validate in mock mode, run approved real optimization, inspect configuration and example insights, iterate, and recommend safety/CI gates. Start here when optimizing a function for the first time. |
| Setup | [traigent-setup-quickstart](skills/traigent-setup-quickstart/) | Install and set up the Traigent SDK — `pip install`, environment variables (`TRAIGENT_API_KEY`), mock mode, evaluation dataset creation in JSONL, and a first `@traigent.optimize` decorated function. |
| Setup | [traigent-setup-decorator](skills/traigent-setup-decorator/) | Configure `@traigent.optimize()` beyond the basics — `EvaluationOptions` (datasets, custom evaluators, scoring), `InjectionOptions` (how optimized configs reach your function), `ExecutionOptions` (sync/async, timeouts, local-only), and multi-objective optimization. |
| Setup | [traigent-setup-integrations](skills/traigent-setup-integrations/) | Integrate Traigent with AI frameworks — LangChain, LiteLLM, and DSPy adapter patterns, multi-provider model testing (OpenAI + Anthropic + Google), `auto_override_frameworks`, and observability via MLflow and Weights & Biases. |
| Dataset | [traigent-dataset-curate](skills/traigent-dataset-curate/) | Build, split, grow, and score Traigent evaluation datasets — assess existing examples, JSONL format and holdout discipline, client-side synthesis with `ExampleSynthesizer`/`optimize_with_guidance(grow_dataset=…)`, backend generation endpoints, post-run example scoring via `ExampleInsightsClient`, and the local content-reflection loop after Traigent flags hard or broken example IDs. |
| Evaluation | [traigent-eval-choose-metric](skills/traigent-eval-choose-metric/) | Choose what to measure before optimizing — the 6-question metric interview, the measure-type vocabulary (accuracy, quality, latency, safety, efficiency, reliability, sanity_check), built-in objective names, multi-objective accuracy+cost patterns, and when a safety property belongs in a gate instead. |
| Evaluation | [traigent-eval-build](skills/traigent-eval-build/) | Wire or implement an evaluator — the 5-tier wire-first ladder (`eval_dataset` → `scoring_function` → `metric_functions` → `custom_evaluator` → `BaseEvaluator`), the `ExampleResult` contract, and deterministic / LLM-judge / statistical / hybrid templates with fail-closed parse handling. |
| Evaluation | [traigent-eval-audit](skills/traigent-eval-audit/) | Audit evaluator and LLM-judge reliability — gold-slice agreement, repetition stability, bias probes (position, length, self-preference), parse-failure policy, threshold calibration, and when to demote a judge to a hybrid gate. |
| Optimize | [traigent-optimize-config-space](skills/traigent-optimize-config-space/) | Define which parameters and task-level structural knobs the optimizer can tune and how — `Range`, `IntRange`, `Choices`, `LogRange` types, text2SQL/RAG/multi-hop structural knob taxonomies, factory presets like `Range.temperature()` and `Choices.model()`, inter-parameter constraints, and `ConfigSpace` bundling. |
| Optimize | [traigent-optimize-composite-knobs](skills/traigent-optimize-composite-knobs/) | Declare and run Traigent composite knobs — cascades, routers, ensembles, self-consistency, best-of-n, self-refine, self-debug, ReAct tool loops, verification gates, mixture-of-experts, and fallback patterns, with StageRunner wiring, telemetry-to-measures merging, and honest calibration-backed claim scope. |
| Optimize | [traigent-optimize-run](skills/traigent-optimize-run/) | Run optimization end-to-end — async/sync execution via `func.optimize()` and `optimize_sync()`, algorithm selection (grid/random today; bayesian/optuna are roadmap, not yet executable), trial limits, cost budgets, `ParallelConfig` for concurrent trials, and `CostLimitExceeded` handling. |
| Analyze | [traigent-analyze-guidance](skills/traigent-analyze-guidance/) | What should this run be, and what next? Three modes in one skill: (A) pre-run — fetch the service run-plan and present objectives/models/knobs/search/budget/offline options, apply preflight, mock dry-run first, launch only on explicit go; (B) post-run, portal-tracked — fetch `traigent next-steps RUN_ID --json` and present the returned posture/command template; (C) offline/local fallback — diagnose flat/noisy/negative results and form the next iteration hypothesis when there's no service payload. Portal-tracked decisions come from Traigent, never local markdown logic. |
| Analyze | [traigent-analyze-results](skills/traigent-analyze-results/) | Inspect `OptimizationResult` objects — best config and score, individual trial comparison, stop-reason interpretation, cost/token usage tracking, and `apply_best_config()` for production deployment. |
| Analyze | [traigent-analyze-variable-importance](skills/traigent-analyze-variable-importance/) | Rank which tuned variables actually drove observed optimization gains — per-value objective spread, variance-decomposition share, bootstrap confidence intervals, honest `significant` vs `directional` labels, and a one-glance SVG summary card. |
| Gate & Debug | [traigent-ci-safety-gate](skills/traigent-ci-safety-gate/) | Gate an optimized agent — candidate-vs-incumbent `PromotionGate`, TVL spec validation, planned in-run `safety_constraints` (not yet implemented), and GitHub Actions checks for safety (holdout regression) and efficiency (cost/latency budgets). |
| Gate & Debug | [traigent-debugging](skills/traigent-debugging/) | Troubleshoot optimization failures — mock mode for CI/CD without API keys, `TRAIGENT_LOG_LEVEL=DEBUG` logging, error-class reference (`CostLimitExceeded`, `ConfigurationError`, `OptimizationStateError`), and missing-dependency diagnosis. |
| JS/TS | [traigent-js](skills/traigent-js/) | Set up and run native JavaScript/TypeScript optimization with `@traigent/sdk` — `optimize(spec)(agentFn)`, `param.*` search spaces, evaluation blocks, trial context, budgets, injection modes, and hybrid config-space authoring. |
| Recipes | [traigent-recipe-text2sql](skills/traigent-recipe-text2sql/) | End-to-end recipe to optimize a text2SQL agent with Traigent and reach high accuracy at low cost. Use when wiring a SPIDER-style NL->SQL agent with @traigent.optimize: execution-match scoring, model + structural knobs, weighted ACL objectives, mock dry-run, then a real portal-tracked run. Captures the working configuration that took a plain agent from 66.7% -> 90% on the cheap model. |

### Renamed in the 2026-07 consolidation (pre-release)

These skills were renamed or merged as part of a taxonomy consolidation. No prior stable release shipped the old names, so this is a straight rename/merge with no deprecation period:

| Old name(s) | New name |
| ----------- | -------- |
| `traigent-quickstart` | `traigent-setup-quickstart` |
| `traigent-decorator-setup` | `traigent-setup-decorator` |
| `traigent-integrations` | `traigent-setup-integrations` |
| `traigent-curate-dataset` | `traigent-dataset-curate` |
| `traigent-choose-metric` | `traigent-eval-choose-metric` |
| `traigent-build-evaluator` | `traigent-eval-build` |
| `traigent-evaluator-audit` | `traigent-eval-audit` |
| `traigent-configuration-space` | `traigent-optimize-config-space` |
| `traigent-composite-knobs` | `traigent-optimize-composite-knobs` |
| `traigent-run-optimization` | `traigent-optimize-run` |
| `show-significant-tuned-variables` | `traigent-analyze-variable-importance` |
| `traigent-text2sql-optimize` | `traigent-recipe-text2sql` |
| `traigent` | `traigent-boost-agent` (merged) |
| `traigent-run-plan` + `traigent-next-run` + `traigent-iterate` | `traigent-analyze-guidance` (merged) |
| `traigent-reflect-hard-examples` | `traigent-dataset-curate` (merged) |

## Install

### As a plugin (recommended — one step, stays in sync)

This repo is a plugin marketplace for Claude Code, OpenAI Codex, and GitHub
Copilot CLI. Installing the `traigent` plugin gives you all 18 skills at once,
namespaced as `traigent:<skill-name>`, with updates delivered through your
agent's normal plugin-update flow.

```bash
# Claude Code
/plugin marketplace add Traigent/traigent-skills
/plugin install traigent@traigent

# OpenAI Codex
codex plugin marketplace add https://github.com/Traigent/traigent-skills
codex plugin add traigent@traigent

# GitHub Copilot CLI
copilot plugin marketplace add Traigent/traigent-skills
copilot plugin install traigent@traigent
```

### Via `npx skills` (cross-agent, pick individual skills)

```bash
# List available skills in this repo
npx skills add Traigent/traigent-skills --list

# Install a specific skill
npx skills add Traigent/traigent-skills --skill traigent-setup-quickstart

# Install several
npx skills add Traigent/traigent-skills \
  --skill traigent-setup-quickstart --skill traigent-js --skill traigent-optimize-run

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
cp -r traigent-skills/skills/traigent-setup-quickstart .agents/skills/

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

### Using with Codex CLI

Codex CLI also does not auto-load a skills directory the way Claude Code does — it only reads
`AGENTS.md`. In a 20-cell simulation wave, 7 of 7 Codex agents ignored mounted skills for exactly
this reason. If you mount these skills into a project (e.g. copied to
`.github/skills/<name>/SKILL.md`), copy the ready-made stanza from
[`templates/AGENTS.md.example`](templates/AGENTS.md.example) into your project's `AGENTS.md` — it
points Codex at the mounted skill files and states the two most load-bearing rules (dry-run first
with offline mode; never mock the real run) inline, so they hold even before Codex opens a skill.

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
- Traigent SDK — `pip install "traigent>=0.19"` (the floor avoids the PyPI placeholder 0.0.1)
- Node.js 18, 20, or 22
- Traigent JS SDK — not published on public npm yet; use the source/link flow in
  `skills/traigent-js` until Traigent/traigent-js#165 lands.

## Maintenance

[`SYNC_MAP.md`](SYNC_MAP.md) maps each skill to the Traigent SDK source files it documents. When the SDK changes, review the corresponding skills for accuracy.

## Skill governance

Skill updates use protected regions, per-skill provenance, and versioned, score-gated changes. `SKILL.md` frontmatter is implicitly protected because YAML must remain first; invariant claim-scope, caveat, and safety constraints are wrapped with `<!-- PROTECTED -->` markers, and each skill has a `provenance.json` document hash. Skills with `references/*.md` files also carry `reference_hashes` in `provenance.json`, refreshed with `python tools/contract/update_reference_hashes.py <skill-dir>`.

Optimizer-proposed edits are accepted only through reviewed PRs that pass a strictly-greater held-out baseline. Marker and provenance adoption keeps existing `metadata.version: "1.0"` values; the version bump discipline starts with the next instructional content change. See [eval-artifacts/README.md](eval-artifacts/README.md).

## License

Apache-2.0 — see [LICENSE](LICENSE). Same as the Traigent SDK.
