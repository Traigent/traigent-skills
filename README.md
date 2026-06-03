# Traigent SDK Skills

User-facing [Agent Skills](https://agentskills.io/) for the **Traigent SDK** — zero-code LLM optimization using decorators. Wrap any function with `@traigent.optimize()`, declare a configuration space, and let Traigent search for the best model / prompt / parameter combination against your eval dataset.

These skills work across **all major AI coding agents**: Claude Code, Cursor, GitHub Copilot, Gemini CLI, OpenAI Codex, Windsurf, Junie, and [30+ more](https://skills.sh/).

> Looking for internal dev/CI/design skills (code review, PR automation, security forensics, UI/UX)? Those live in the internal [`Traigent/agents-skills`](https://github.com/Traigent/agents-skills) repo. **This repo holds only the user-facing SDK skills.**

## Skills

These skills guide your agent through the full Traigent optimization lifecycle, in roughly the order you'd use them:

| Skill | Description |
| ----- | ----------- |
| [traigent-quickstart](skills/traigent-quickstart/) | Install and set up the Traigent SDK — `pip install`, environment variables (`TRAIGENT_API_KEY`), mock mode, eval dataset creation in JSONL, and a first `@traigent.optimize` decorated function. |
| [traigent](skills/traigent/) | The end-to-end driver: setup → **dry-run validation (mock mode)** → real execution. Always validates the full pipeline in mock mode before spending on real API calls. Start here when optimizing a function for the first time. |
| [traigent-configuration-space](skills/traigent-configuration-space/) | Define which parameters the optimizer can tune and how — `Range`, `IntRange`, `Choices`, `LogRange` types, factory presets like `Range.temperature()` and `Choices.model()`, inter-parameter constraints, and `ConfigSpace` bundling. |
| [traigent-decorator-setup](skills/traigent-decorator-setup/) | Configure `@traigent.optimize()` beyond the basics — `EvaluationOptions` (datasets, custom evaluators, scoring), `InjectionOptions` (how optimized configs reach your function), `ExecutionOptions` (sync/async, timeouts, local-only), and multi-objective optimization. |
| [traigent-run-optimization](skills/traigent-run-optimization/) | Run optimization end-to-end — async/sync execution via `func.optimize()` and `optimize_sync()`, algorithm selection (grid, random, bayesian, optuna), trial limits, cost budgets, `ParallelConfig` for concurrent trials, and `CostLimitExceeded` handling. |
| [traigent-analyze-results](skills/traigent-analyze-results/) | Inspect `OptimizationResult` objects — best config and score, individual trial comparison, stop-reason interpretation, cost/token usage tracking, and `apply_best_config()` for production deployment. |
| [traigent-integrations](skills/traigent-integrations/) | Integrate Traigent with AI frameworks — LangChain, LiteLLM, and DSPy adapter patterns, multi-provider model testing (OpenAI + Anthropic + Google), `auto_override_frameworks`, and observability via MLflow and Weights & Biases. |
| [traigent-debugging](skills/traigent-debugging/) | Troubleshoot optimization failures — mock mode for CI/CD without API keys, `TRAIGENT_LOG_LEVEL=DEBUG` logging, error-class reference (`CostLimitExceeded`, `ConfigurationError`, `OptimizationStateError`), and missing-dependency diagnosis. |

## Install

### Via `npx skills` (recommended)

```bash
# List available skills in this repo
npx skills add Traigent/traigent-skills --list

# Install a specific skill
npx skills add Traigent/traigent-skills --skill traigent-quickstart

# Install several
npx skills add Traigent/traigent-skills \
  --skill traigent-quickstart --skill traigent-configuration-space --skill traigent-run-optimization

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

The skills *teach your agent to drive the Traigent SDK*, so to actually run an optimization you'll need the SDK in your own project:

- Python 3.11–3.13
- Traigent SDK — `pip install traigent`

## Maintenance

[`SYNC_MAP.md`](SYNC_MAP.md) maps each skill to the Traigent SDK source files it documents. When the SDK changes, review the corresponding skills for accuracy.

## License

Apache-2.0 — see [LICENSE](LICENSE). Same as the Traigent SDK.
