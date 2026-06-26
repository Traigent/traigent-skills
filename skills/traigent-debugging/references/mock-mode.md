# Mock Mode Reference

> **Migration note (current SDK):** Mock mode activation is now an in-code call:
>
> ```python
> from traigent.testing import enable_mock_mode_for_quickstart
> enable_mock_mode_for_quickstart()
> ```
>
> The legacy `TRAIGENT_MOCK_LLM=true` env var still works in non-production environments for backward compatibility, but **is hard-blocked when `ENVIRONMENT=production`** (raises `OSError` at SDK import). All examples below that set `TRAIGENT_MOCK_LLM=true` continue to work in dev/test; new code should use the in-code API for clarity and code-review visibility.

## Overview

Traigent supports two ways to activate mock mode:

| Path | When to use |
|---|---|
| `traigent.testing.enable_mock_mode_for_quickstart()` (in code) | Recommended. Production-blocked. |
| `TRAIGENT_MOCK_LLM=true` (env var) | Legacy fallback. Honored only outside production. |

For zero-egress testing, pass `offline=True` on the decorator or optimization call. Mock
mode controls provider-call interception; `offline=True` controls Traigent backend egress and
portal result sync.

## Enabling Mock Mode

### Environment Variables

```bash
# Legacy fallback for mock LLM responses
export TRAIGENT_MOCK_LLM=true

# Then run your code
python my_optimization.py
```

### In Python

```python
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
```

### In pytest

```python
import pytest

@pytest.fixture(autouse=True)
def mock_traigent_env(monkeypatch):
    monkeypatch.setenv("TRAIGENT_MOCK_LLM", "true")
```

Or via pytest CLI:

```bash
TRAIGENT_MOCK_LLM=true pytest tests/
```

## What TRAIGENT_MOCK_LLM Does

When `TRAIGENT_MOCK_LLM=true`:

- LLM API calls return synthetic/mock responses instead of calling real providers
- No API keys are required (OpenAI, Anthropic, etc.)
- No network calls are made to LLM providers
- Cost tracking reports zero or minimal cost
- Response times are near-instant

### What Gets Mocked

- **LiteLLM** completion calls (`litellm.completion` / `litellm.acompletion`)
- **LangChain** LLM wrappers (`ChatOpenAI`, `ChatAnthropic`, etc.) when constructed inside the decorated function

### What Is NOT Mocked

> **Important:** Raw `openai` and `anthropic` clients are **not** intercepted by mock mode. If your function calls `openai.OpenAI().chat.completions.create(...)` or `anthropic.Anthropic().messages.create(...)` directly, those calls will reach the real API. Use `litellm.completion()` or LangChain wrappers for a fully keyless mock-mode experience.

- Raw `openai.OpenAI` / `openai.AsyncOpenAI` clients
- Raw `anthropic.Anthropic` / `anthropic.AsyncAnthropic` clients
- Your own function logic (runs normally)
- Evaluator functions (run normally)
- Dataset loading and validation
- Configuration space sampling
- The optimization loop itself

This means mock mode is useful for testing:
- Configuration space setup
- Evaluator logic
- Dataset format
- End-to-end optimization flow
- CI/CD pipeline integration

## What `offline=True` Does

When `offline=True`:

- No connection to the Traigent cloud backend
- Results are stored locally only
- No experiment syncing or portal dashboard updates
- No authentication required

Use this when:
- Running on a machine without internet access
- Running in CI/CD where the backend is not available
- Developing locally without a backend service
- Testing the SDK in isolation

## Using Mock Mode with `offline=True`

The most common zero-egress validation pattern is to enable mock mode and pass `offline=True`:

```python
import traigent
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()

@traigent.optimize(
    eval_dataset="data.jsonl",
    configuration_space={"model": ["gpt-4o-mini"], "temperature": [0.0, 0.5]},
    objectives=["accuracy"],
    offline=True,
)
def my_func(text):
    config = traigent.get_config()
    return f"Response using {config['model']}"

results = my_func.optimize_sync(max_trials=3)
```

This gives you a fully self-contained environment:
- No API keys needed
- No backend connection needed
- No network calls at all
- Fast execution (no real LLM latency)

## Limitations of Mock Mode

Mock mode has important limitations to be aware of:

1. **Mock responses are not realistic**: The mock LLM returns synthetic text, not real model outputs. Do not use mock mode to evaluate actual model quality.

2. **Cost is not accurate**: Mock mode reports zero or minimal cost. Use real API calls for cost estimation.

3. **Latency is not representative**: Mock calls return instantly. Real optimization takes longer due to API latency.

4. **Provider-specific behavior is not simulated**: Rate limits, token limits, and provider-specific formatting are not mocked.

5. **Evaluator scores under mock — deterministic scorers will see uniform 0.0:** The mock
   LLM always returns the same constant string (`"This is a mock response for testing."`,
   `traigent/integrations/utils/mock_adapter.py:69`). For **output-based / deterministic
   scorers** (exact-match, JSON-schema, SQL execution accuracy), every trial scores 0.0
   because no output-based scorer can reward the constant mock text. This is **expected and
   correct** — it means mock-plumbing is working, not that your agent is broken.
   Config-aware scorers (those that read `traigent.get_config()`) will still produce varied
   scores across trials, even in mock mode.

## Example: CI/CD Pipeline

```yaml
# .github/workflows/test.yml
name: Test Optimization Setup
on: [push]
jobs:
	  test:
	    runs-on: ubuntu-latest
	    env:
	      TRAIGENT_MOCK_LLM: "true"
	    steps:
	      - uses: actions/checkout@v4
	      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install traigent[dev]
      - run: pytest tests/
```

## Example: Quick Validation Script

Validate your optimization setup before spending API budget:

```python
import traigent
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()

@traigent.optimize(
    eval_dataset="data.jsonl",
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.5, 1.0],
    },
    objectives=["accuracy"],
    max_trials=3,
    offline=True,
)
def my_func(text):
    config = traigent.get_config()
    return f"Response using {config['model']}"

# Quick validation run
results = my_func.optimize_sync()

print(f"Ran {len(results.trials)} trials")
print(f"Stop reason: {results.stop_reason}")
print(f"Best config: {results.best_config}")
print("Setup is valid - ready for real optimization")
```

## Disabling Mock Mode

For the legacy env-var path, remove or unset the variable:

```bash
unset TRAIGENT_MOCK_LLM
```

Or set to any value other than `true`:

```bash
export TRAIGENT_MOCK_LLM=false
```
