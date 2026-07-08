# LiteLLM Multi-Provider Reference

> **Dry-run before any real multi-provider run.** Especially for multi-provider sweeps (multiple providers × temperatures × max_tokens × trials can mean hundreds or thousands of LLM calls). Always activate `enable_mock_mode_for_quickstart()`, run, review the cost estimate, and get explicit approval before a real run. See the `traigent-boost-agent` skill for the mandatory dry-run-first / cost-approval workflow.

> **Verify every model ID is LIVE before a real run.** Provider catalogs change constantly — models get delisted, renamed, or quietly re-routed to a retired backend. A dead ID is not a harmless typo: it surfaces as a 404, or (worse) a *degraded run* where one trial silently fails or its cost stays unpriced ($0.00) because the ID isn't in the pricing table. Every model ID in this reference was valid when written and **must be re-checked against each provider's live catalog before you use it** — treat them as illustrative, not evergreen. See [Verifying model availability](#verifying-model-availability) below.

> **Give reasoning models enough `max_tokens` headroom.** Reasoning models (`gemini-2.5`/`3.x`, `gpt-5`, the `o`-series) spend hidden reasoning tokens that count against `max_tokens` *before* any answer text is produced. A cap sized for a normal model (e.g. `256`/`512`) can be entirely consumed by reasoning, truncating the answer mid-output (`finish_reason=length`). The capable model then scores *far below* a cheap non-reasoning one as a pure measurement artifact, not a real quality gap. Sweep reasoning models with ample headroom (**≥1024–2048**) — the examples below use headroom-safe values because their model pools mix reasoning and non-reasoning models; sweep low caps only in a space with no reasoning models. Field-observed: `gemini-2.5-pro` at `max_tokens=256` spent 241 tokens reasoning and emitted a truncated query (~23% of the expected output); at `1536` it completed correctly.

## Overview

LiteLLM provides a unified `completion()` API that works across 100+ LLM providers. Combined with Traigent, you can optimize model selection across providers in a single optimization run.

## Installation

```bash
pip install "traigent>=0.19" litellm
```

Set API keys for each provider you want to test:

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export COHERE_API_KEY="..."
export MISTRAL_API_KEY="..."
```

## Supported Providers

LiteLLM uses model name prefixes to route to the correct provider. Common providers:

| Provider | Model Prefix | Example |
|---|---|---|
| OpenAI | (none) | `gpt-4o-mini`, `gpt-4o` |
| Anthropic | `anthropic/` or none | `claude-3-haiku-20240307`, `claude-3-5-sonnet-20241022` |
| Google Gemini | `gemini/` | `gemini/gemini-3-flash`, `gemini/gemini-3.1-pro` |
| Mistral | `mistral/` | `mistral/mistral-small-latest` |
| Cohere | `command-r` | `command-r`, `command-r-plus` |
| AWS Bedrock | `bedrock/` | `bedrock/anthropic.claude-3-sonnet-20240229-v1:0` |
| Azure OpenAI | `azure/` | `azure/my-deployment` |
| Together AI | `together_ai/` | `together_ai/meta-llama/Llama-3-70b-chat-hf` |
| Groq | `groq/` | `groq/llama3-70b-8192` |
| OpenRouter | `openrouter/` | `openrouter/openai/gpt-4o-mini`, `openrouter/anthropic/claude-3-haiku`, `openrouter/google/gemini-2.5-flash-lite` |

The example IDs above were live when written; **re-verify them** before use (see the next
section). Prefer a specific versioned ID (e.g. `claude-3-haiku-20240307`) over a moving
`-latest` alias — pinned versions price reliably, whereas an alias can resolve to a model
whose pricing isn't in the table yet (unpriced `$0.00` cost). See the LiteLLM documentation
for the full provider list.

## Verifying model availability

Catalogs drift. Before any real run, confirm each model ID is both **routable** (the
provider still serves it) and **price-recognized** (so cost tracking and `cost_limit`
actually work). Two real-world failures we have hit:

- `openrouter/google/gemini-flash-1.5-8b` — **delisted**; returns a 404 from the live
  OpenRouter catalog.
- `openrouter/anthropic/claude-3.5-haiku` — routes to a **retired** Amazon Bedrock
  endpoint; the trial degrades instead of erroring cleanly.

**SDK-native preflight (recommended).** The CLI validates an ID against a provider's known
model list without spending anything:

```bash
# List a provider's known model IDs, or validate a specific one (valid: true/false)
traigent models --provider openai
traigent models --provider anthropic --check claude-3-haiku-20240307
traigent models --provider gemini --check gemini-3-flash --json
```

**Query the provider catalog directly.** When a provider isn't covered by `traigent models`
(e.g. OpenRouter), hit its live catalog endpoint and grep for the exact ID:

```bash
# OpenRouter: the slug after "openrouter/" must appear in the live catalog
curl -s https://openrouter.ai/api/v1/models | grep -o '"id":"[^"]*"' | sort
# OpenAI:    curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
# Together:  curl -s https://api.together.xyz/v1/models -H "Authorization: Bearer $TOGETHER_API_KEY"
# Anthropic: curl -s https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01"
```

If an ID is missing from the live list, swap it for one that is — do not assume an ID that
worked last month still resolves today.

## Basic Multi-Provider Example

```python
import traigent
import litellm

@traigent.optimize(
    eval_dataset="qa_eval.jsonl",
    configuration_space={
        # Re-verify these IDs are live + priced before running (see "Verifying
        # model availability"); catalogs change and dead IDs cause 404s / $0.00 cost.
        "model": [
            "gpt-4o-mini",
            "gpt-4o",
            "claude-3-haiku-20240307",
            "claude-3-5-sonnet-20241022",
            "gemini/gemini-3-flash",
        ],
        "temperature": [0.0, 0.3, 0.7],
        "max_tokens": [1024, 2048],  # headroom-safe: the pool includes a reasoning model (see note above)
    },
    objectives=["accuracy"],
    max_trials=15,
)
def answer(question):
    config = traigent.get_config()

    response = litellm.completion(
        model=config["model"],
        messages=[{"role": "user", "content": question}],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
    )
    return response.choices[0].message.content

results = answer.optimize_sync()
```

## Cost Tracking

LiteLLM tracks cost per completion call. You can access this through Traigent's results:

```python
results = answer.optimize_sync()

# Traigent aggregates cost across all trials
if results.total_cost is not None:
    print(f"Total optimization cost: ${results.total_cost:.4f}")

# Per-trial cost analysis
for trial in results.successful_trials:
    model = trial.config["model"]
    accuracy = trial.get_metric("accuracy", 0.0)
    print(f"{model}: accuracy={accuracy:.2%}")

# Compare cost vs accuracy across providers
stats = results.experiment_stats
print(f"Cost per config: ${stats.cost_per_configuration:.4f}")
```

### Cost-Accuracy Tradeoff Analysis

```python
results = answer.optimize_sync()

# Group trials by provider
from collections import defaultdict
provider_results = defaultdict(list)

for trial in results.successful_trials:
    model = trial.config["model"]
    # Extract provider from model name
    if "/" in model:
        provider = model.split("/")[0]
    elif model.startswith("claude"):
        provider = "anthropic"
    elif model.startswith("gpt"):
        provider = "openai"
    else:
        provider = "other"
    provider_results[provider].append(trial)

for provider, trials in provider_results.items():
    avg_acc = sum(t.get_metric("accuracy", 0.0) for t in trials) / len(trials)
    print(f"{provider}: avg accuracy={avg_acc:.2%} ({len(trials)} trials)")
```

## Complete Multi-Provider Example with Fallback

```python
import traigent
import litellm

@traigent.optimize(
    eval_dataset="eval_prompts.jsonl",
    configuration_space={
        # Re-verify these IDs are live + priced before running (catalogs change).
        "model": [
            "gpt-4o-mini",
            "gpt-4o",
            "claude-3-haiku-20240307",
            "claude-3-5-sonnet-20241022",
            "gemini/gemini-3-flash",
            "gemini/gemini-3.1-pro",
        ],
        "temperature": [0.0, 0.3, 0.5, 0.7],
        "max_tokens": [1024, 2048],  # headroom-safe: the pool includes reasoning models (see note above)
    },
    objectives=["accuracy"],
    max_trials=20,
)
def generate_response(prompt):
    config = traigent.get_config()

    response = litellm.completion(
        model=config["model"],
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
    )
    return response.choices[0].message.content


# Run optimization
results = generate_response.optimize_sync()

# Analyze results
print(f"Best model: {results.best_config['model']}")
print(f"Best temperature: {results.best_config['temperature']}")
print(f"Best score: {results.best_score:.3f}")
print(f"Total cost: ${results.total_cost:.4f}" if results.total_cost else "Cost not tracked")
print(f"Trials: {len(results.successful_trials)}/{len(results.trials)} successful")

# Apply best config
if results.best_score is not None and results.best_score >= 0.8:
    generate_response.apply_best_config(results)
    # Now generate_response() uses the best model/temperature/max_tokens
```

## Tips

- LiteLLM handles retries and fallbacks internally; Traigent optimizes the model choice
- Set `LITELLM_LOG=DEBUG` for detailed provider-level logging
- Use `litellm.set_verbose = True` during development to see API calls
- Some providers require additional setup (Azure needs deployment names, Bedrock needs AWS credentials)
- LiteLLM's cost tracking works automatically for most providers
