# Mock Mode Reference

> **Migration note (current SDK):** Mock mode activation is now an in-code call:
>
> ```python
> from traigent.testing import enable_mock_mode_for_quickstart
> enable_mock_mode_for_quickstart()
> ```
>
> The legacy `TRAIGENT_MOCK_LLM=true` env var is **deprecated**: on traigent 0.27.0 it emits a DeprecationWarning (hidden by default) saying it "will be removed in a future release". It still works in non-production environments for backward compatibility, but **is hard-blocked when `ENVIRONMENT=production`** (raises `OSError`). The block does **not** fire at `import traigent` — a bare import succeeds even with both set. It fires the first time env config is loaded (decoration/CLI/`optimize()`), so on the decorator path the earliest you'll see it is at `@traigent.optimize(...)` (any `traigent` CLI command raises it too). The examples below lead with the in-code API; the env-var forms are kept, marked deprecated, only for existing setups. Use `enable_mock_mode_for_quickstart()` in code, e.g. from a pytest fixture/conftest, for new setups.

## Overview

Traigent supports two ways to activate mock mode:

| Path | When to use |
|---|---|
| `traigent.testing.enable_mock_mode_for_quickstart()` (in code) | Recommended. Production-blocked. |
| `TRAIGENT_MOCK_LLM=true` (env var) | Deprecated legacy fallback, scheduled for removal. Honored only outside production. |

For zero Traigent backend egress, pass `offline=True` on the decorator or optimization call. Mock
mode controls provider-call interception; `offline=True` controls Traigent backend egress and
portal result sync. Neither stops other traffic: provider calls that mock mode does not intercept
still go out, and `import litellm` fetches LiteLLM's public pricing map over the network unless
`LITELLM_LOCAL_MODEL_COST_MAP=True` is set before that import.

## Enabling Mock Mode

### In Python

```python
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
```

### In pytest

Activation is process-local and cannot be switched off in the same process, so enable it
once for a test session that should run fully mocked, e.g. in `tests/conftest.py`:

```python
import pytest
from traigent.testing import enable_mock_mode_for_quickstart


@pytest.fixture(autouse=True, scope="session")
def traigent_mock_mode():
    enable_mock_mode_for_quickstart()
```

### Environment variable (deprecated)

`TRAIGENT_MOCK_LLM=true` is deprecated on traigent 0.27.0 (a DeprecationWarning, hidden by default, says it "will be removed in a future release"). Use `traigent.testing.enable_mock_mode_for_quickstart()` in code, e.g. from a pytest fixture/conftest, for new setups.

```bash
# Deprecated legacy fallback; prefer enable_mock_mode_for_quickstart() in code
export TRAIGENT_MOCK_LLM=true
python my_optimization.py

# Deprecated: the same, for one pytest run
TRAIGENT_MOCK_LLM=true pytest tests/
```

## What Mock Mode Does

When mock mode is active (`enable_mock_mode_for_quickstart()`, or the deprecated `TRAIGENT_MOCK_LLM=true`):

- LLM API calls return synthetic/mock responses instead of calling real providers
- No API keys are required (OpenAI, Anthropic, etc.)
- No network calls are made to LLM providers for the calls it intercepts (see "What Is NOT Mocked" below)
- Runtime cost limits still apply. Released SDKs through 0.30.0 can reject every
  trial at a very low `TRAIGENT_RUN_COST_LIMIT` because of their initial reservation.
  On SDK develop after the observed-mean admission change (the 0.31 line), the
  first sequential trial starts before a cost estimate exists. Reported zero-cost
  trials can continue; positive reported costs can stop later trials with
  `stop_reason="cost_limit"`. An explicit cap with a completed trial that reports
  no cost is refused; unknown cost is different from reported zero. The cap does
  not guarantee that the first trial's actual cost fits within it.
- Response times are near-instant

### A mock run is still priced and gated (SDK 0.31.0+)

From SDK 0.31.0 the pre-run cost estimate runs for a mock run too, and `CostLimitExceeded` can
fire before trial 1 on a large dataset even though nothing would be spent (for example a 46-row
dataset of several thousand input tokens per row against the $2.00 default). SDKs before 0.31.0
skipped the estimate in mock mode. The refusal text only offers `TRAIGENT_RUN_COST_LIMIT` and
`TRAIGENT_COST_APPROVED=true`; for a mock run use neither (approval would carry into the real
run). Instead:

- Dry-run a **small slice** (5-10 rows) of the dataset. This works on every SDK version.
- Or, for a test-only run, set `TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT=1` together with an explicit
  non-production environment (`ENVIRONMENT=development`; `test`, `testing`, `local`, `dev`,
  `stage` and `staging` also qualify). With the environment unset, `ci` or production the
  exemption is ignored and the estimate applies. It also requires mock mode to be on.

### What Gets Mocked

- **LiteLLM** completion calls (`litellm.completion` / `litellm.acompletion`). From SDK 0.31.0 the
  interceptors are installed when mock mode is enabled, so a standalone `litellm.completion`
  made right after `enable_mock_mode_for_quickstart()` (no evaluator, no optimization run) gets
  the canned reply. Before 0.31.0 they were installed only once an evaluator was built.
- **LangChain** LLM wrappers (`ChatOpenAI`, `ChatAnthropic`, etc.) when constructed inside the decorated function

### What Is NOT Mocked

> **Important:** Raw `openai` and `anthropic` clients are **not** intercepted by mock mode: they get no canned reply. If your function calls `openai.OpenAI().chat.completions.create(...)` or `anthropic.Anthropic().messages.create(...)` directly, then on SDK 0.31.0+ the HTTP request to a known LLM provider host (the major hosted APIs, Azure OpenAI and Bedrock runtime endpoints) is blocked with `MockModeTransportBlockedError`, not billed. The block covers requests sent through httpx, aiohttp and requests; a `boto3` call and hosts outside the SDK's list are not blocked. On SDKs before 0.31.0 those calls reach the real API. Use `litellm.completion()` or LangChain wrappers for a fully keyless mock-mode experience.

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

The most common validation pattern with zero Traigent backend egress is to enable mock mode and pass `offline=True`:

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

This gives you a self-contained environment:
- No API keys needed
- No backend connection needed (zero Traigent backend egress)
- No provider calls for LiteLLM/LangChain calls, which mock mode intercepts; a raw `openai` /
  `anthropic` client in the function gets no canned reply and, on SDK 0.31.0+, its requests to
  known provider hosts are blocked rather than billed (before 0.31.0 it still calls the provider;
  `boto3` and unlisted hosts are not blocked on any version)
- If your code imports `litellm` itself, set `LITELLM_LOCAL_MODEL_COST_MAP=True` before that
  import, or LiteLLM fetches its public pricing map over the network
- Fast execution (no real LLM latency)

## Limitations of Mock Mode

Mock mode has important limitations to be aware of:

1. **Mock responses are not realistic**: The mock LLM returns synthetic text, not real model outputs. Do not use mock mode to evaluate actual model quality.

2. **Cost is not accurate**: Mock mode reports zero or minimal cost. Use real API calls for cost estimation.

3. **Latency is not representative**: Mock calls return instantly. Real optimization takes longer due to API latency.

4. **Provider-specific behavior is not simulated**: Rate limits, token limits, and provider-specific formatting are not mocked.

5. **Evaluator scores under mock — it depends on whether the scorer parses the reply.** The mock
   LLM always returns the same constant string (`"This is a mock response for testing."`,
   `traigent/integrations/utils/mock_adapter.py:69`).
   - A scorer that **returns a number for any input** (exact-match, SQL execution accuracy, one
     that catches its own parse errors) scores every trial 0.0, because no output-based scorer
     can reward the constant mock text. This is **expected and correct**: mock plumbing is
     working, not your agent broken. Config-aware scorers (those that read
     `traigent.get_config()`) still produce varied scores across trials.
   - A scorer that **parses the reply** (`json.loads`, JSON-schema validation, a
     structured-output parser) raises on the canned text. The SDK refuses to substitute a
     fabricated 0.0, so **every trial fails**: `All trials failed — no examples succeeded`,
     `best_score` is `None`, and the process exits 0. This is **also expected under mock**, not a
     broken pipeline. Do not wrap the scorer to swallow the error and return 0.0. Instead make
     the agent return valid JSON before the model call while mock mode is on (a stub deleted for
     the real run), or use a config-aware mock-only demo scorer. LiteLLM's `mock_response=`
     argument does not help on SDK 0.31.1: Traigent's interception overrides it
     (Traigent/Traigent#2798). A scorer unwrapping `traigent.with_usage(...)` reads
     `output["text"]` (see `traigent-boost-agent` `references/instrument-recipe.md`).

## Example: CI/CD Pipeline

```yaml
# .github/workflows/test.yml
name: Test Optimization Setup
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      # tests/conftest.py enables mock mode in code (see "In pytest" above)
      TRAIGENT_RUN_APPROVED: "1"   # under GITHUB_ACTIONS every optimize() — mock included — refuses to run without this
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install "traigent[dev]>=0.24.0"
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

The in-code activation lasts until the process exits; run the real optimization in a process
that never calls `enable_mock_mode_for_quickstart()`. For the deprecated env-var path, remove or
unset the variable:

```bash
unset TRAIGENT_MOCK_LLM
```

Or set to any value other than `true`:

```bash
export TRAIGENT_MOCK_LLM=false
```
