# Traigent SDK Skills

User-facing [Agent Skills](https://agentskills.io/) for the **Traigent SDKs** — zero-code LLM optimization using the Python decorator flow or the native JavaScript/TypeScript SDK. Wrap a Python function with `@traigent.optimize()` or a JS/TS function with `optimize(spec)(agentFn)`, declare a configuration space, and let Traigent search for the best model / prompt / parameter combination against your eval dataset.

These skills work across **all major AI coding agents**: Claude Code, Cursor, GitHub Copilot, Gemini CLI, OpenAI Codex, Windsurf, Junie, and [30+ more](https://skills.sh/).

> Looking for internal dev/CI/design skills (code review, PR automation, security forensics, UI/UX)? Those live in the internal [`Traigent/agents-skills`](https://github.com/Traigent/agents-skills) repo. **This repo holds only the user-facing SDK skills.**

## Skills

These skills guide your agent through the full Traigent optimization lifecycle, in roughly the order you'd use them:

| Skill | Description |
| ----- | ----------- |
| [traigent-quickstart](skills/traigent-quickstart/) | Install and set up the Traigent SDK — `pip install`, environment variables (`TRAIGENT_API_KEY`), mock mode, eval dataset creation in JSONL, and a first `@traigent.optimize` decorated function. |
| [traigent](skills/traigent/) | The end-to-end driver: setup → **dry-run validation (mock mode)** → real execution. Always validates the full pipeline in mock mode before spending on real API calls. Start here when optimizing a function for the first time. |
| [traigent-js](skills/traigent-js/) | Set up and run native JavaScript/TypeScript optimization with `@traigent/sdk` — `optimize(spec)(agentFn)`, `param.*` search spaces, evaluation blocks, trial context, budgets, injection modes, and hybrid config-space authoring. |
| [traigent-configuration-space](skills/traigent-configuration-space/) | Define which parameters the optimizer can tune and how — `Range`, `IntRange`, `Choices`, `LogRange` types, factory presets like `Range.temperature()` and `Choices.model()`, inter-parameter constraints, and `ConfigSpace` bundling. |
| [traigent-decorator-setup](skills/traigent-decorator-setup/) | Configure `@traigent.optimize()` beyond the basics — `EvaluationOptions` (datasets, custom evaluators, scoring), `InjectionOptions` (how optimized configs reach your function), `ExecutionOptions` (sync/async, timeouts, local-only), and multi-objective optimization. |
| [traigent-run-optimization](skills/traigent-run-optimization/) | Run optimization end-to-end — async/sync execution via `func.optimize()` and `optimize_sync()`, algorithm selection (grid, random, bayesian, optuna), trial limits, cost budgets, `ParallelConfig` for concurrent trials, and `CostLimitExceeded` handling. |
| [traigent-analyze-results](skills/traigent-analyze-results/) | Inspect `OptimizationResult` objects — best config and score, individual trial comparison, stop-reason interpretation, cost/token usage tracking, and `apply_best_config()` for production deployment. |
| [traigent-integrations](skills/traigent-integrations/) | Integrate Traigent with AI frameworks — LangChain, LiteLLM, and DSPy adapter patterns, multi-provider model testing (OpenAI + Anthropic + Google), `auto_override_frameworks`, and observability via MLflow and Weights & Biases. |
| [traigent-debugging](skills/traigent-debugging/) | Troubleshoot optimization failures — mock mode for CI/CD without API keys, `TRAIGENT_LOG_LEVEL=DEBUG` logging, error-class reference (`CostLimitExceeded`, `ConfigurationError`, `OptimizationStateError`), and missing-dependency diagnosis. |
| [traigent-structural-spine](skills/traigent-structural-spine/) | Author a *structural* configuration spine (not just model + one prompt string) when turning an `@traigent.optimize` evaluator into an optimizer — structural knob taxonomy for text2SQL (schema context, generation path, few-shot, candidate voting, repair) and RAG / multi-hop QA (retriever, retrieval-k, query decomposition, context order, answer path, self-consistency), the before/after decorator diff, and a local-optimizer operational checklist. |
| [traigent-composite-knobs](skills/traigent-composite-knobs/) | Declare and run Traigent composite knobs — cascades, routers, ensembles, self-consistency, best-of-n, self-refine, self-debug, ReAct tool loops, verification gates, mixture-of-experts, and fallback patterns, with StageRunner wiring, telemetry-to-measures merging, and honest calibration-backed claim scope. |
| [traigent-boost-agent](skills/traigent-boost-agent/) | Add Traigent to an existing client agent codebase end-to-end — analyze LLM call sites and agent shape, select TVARs with `recommend_configuration_space()`, choose a composite pattern, instrument `@traigent.optimize` minimally, validate in mock mode, run real optimization with cost limits, and report baseline-vs-winner results honestly. |
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
- Traigent JS SDK — `npm install @traigent/sdk`

## Maintenance

[`SYNC_MAP.md`](SYNC_MAP.md) maps each skill to the Traigent SDK source files it documents. When the SDK changes, review the corresponding skills for accuracy.

## Skill governance

Skill updates use protected regions, per-skill provenance, and versioned, score-gated changes. `SKILL.md` frontmatter is implicitly protected because YAML must remain first; invariant claim-scope, caveat, and safety constraints are wrapped with `<!-- PROTECTED -->` markers, and each skill has a `provenance.json` document hash.

Optimizer-proposed edits are accepted only through reviewed PRs that pass a strictly-greater held-out baseline. Marker and provenance adoption keeps existing `metadata.version: "1.0"` values; the version bump discipline starts with the next instructional content change. See [skill-evals/README.md](skill-evals/README.md).

## License

Apache-2.0 — see [LICENSE](LICENSE). Same as the Traigent SDK.
