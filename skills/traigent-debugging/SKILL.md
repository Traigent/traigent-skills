---
name: traigent-debugging
description: "Debug and troubleshoot Traigent optimization issues. Use when encountering CostLimitExceeded, ConfigurationError, OptimizationStateError, ModuleNotFoundError, or when optimization produces unexpected results. Covers mock mode, logging configuration, and common error resolution."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.2"
---

# Debugging and Troubleshooting Traigent

## When to Use

Use this skill when:

- An optimization run fails or produces unexpected results
- You encounter a Traigent exception (CostLimitExceeded, ConfigurationError, etc.)
- You need to test without real API keys (mock mode)
- You want to increase logging verbosity for diagnosis
- Your function works standalone but fails during optimization
- Import errors occur due to missing optional dependencies

## Quick Diagnostic

Enable detailed logging to see what Traigent is doing at each step:

```bash
# Full SDK verbose logging (SDK infrastructure, sampling, backend comms)
export TRAIGENT_LOG_LEVEL=DEBUG  # read on all current SDK versions

# Full tracebacks for ConfigurationError (shows raw exception, not user-friendly message)
export TRAIGENT_DEBUG=1
```

These are distinct: `TRAIGENT_LOG_LEVEL=DEBUG` is for SDK-level verbose output; `TRAIGENT_DEBUG=1` is specifically for showing raw ConfigurationError tracebacks.

Then run your optimization. Debug output includes:
- Configuration sampling decisions
- Trial execution start/stop/status
- Metric extraction and scoring
- Cost tracking per trial
- Backend communication for cloud smart optimization and portal result sync

## Common Errors

### ConfigurationError

**When raised**: Invalid or malformed configuration values, unsupported features, missing required configuration.

Note the two cases below raise **different** exception types, neither of which is
`ConfigurationError` — catch `ValidationError`/`TraigentError`, or a bare `ValueError`
for the empty-space case:

```
# Non-list parameter value:
traigent.utils.exceptions.ValidationError: Validation failed:
configuration_space.model: Parameter must be a list of values or a (min, max) tuple
```

```python
# WRONG: configuration_space values must be lists -> raises ValidationError
@traigent.optimize(
    configuration_space={"model": "gpt-4o-mini"},  # String, not list
)

# CORRECT
@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini"]},  # List
)
```

```python
# WRONG: empty configuration space -> raises a builtin ValueError
#        ("Configuration space cannot be empty..."), NOT a TraigentError
@traigent.optimize(
    configuration_space={},
)

# CORRECT: at least one parameter to optimize
@traigent.optimize(
    configuration_space={"temperature": [0.0, 0.5, 1.0]},
)
```

Set `TRAIGENT_DEBUG=1` to see the full traceback instead of the clean error message.

### CostLimitExceeded

**When raised**: Accumulated API cost exceeds the configured budget. Has `accumulated` and `limit` attributes.

```
traigent.utils.exceptions.CostLimitExceeded: Cost limit exceeded: $0.52 >= $0.50 USD
```

**Fixes**:

```python
# Option 1: Increase the cost limit
@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
    cost_limit=2.0,  # $2.00 USD
)

# Option 2: Use cheaper models
@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini"]},  # Cheaper than gpt-4o
)

# Option 3: Reduce trials
@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
    max_trials=5,  # Fewer trials = lower cost
)
```

**Handling programmatically**:

```python
from traigent.utils.exceptions import CostLimitExceeded

try:
    results = func.optimize_sync()
except CostLimitExceeded as e:
    print(f"Budget exceeded: spent ${e.accumulated:.2f} of ${e.limit:.2f} limit")
    # Check if partial results are available
```

### OptimizationStateError

**When raised**: Accessing configuration in an invalid lifecycle state.

```
traigent.utils.exceptions.OptimizationStateError: Cannot access config outside of optimization trial
```

**Common causes** — note the two distinct failure modes:

```python
# Case A: a bare get_config() with no active trial and nothing applied
traigent.get_config()  # raises OptimizationStateError

# Case B: directly calling a decorated function before optimize()/apply_best_config()
@traigent.optimize(...)
def my_func(text):
    config = traigent.get_config()
    return config["model"]

# The wrapper supplies a (default/empty) config dict, so get_config() itself does NOT
# raise here — but the missing key does:
my_func("hello")  # KeyError: 'model'  (NOT OptimizationStateError)

# CORRECT: run optimization first, then apply
results = my_func.optimize_sync()
my_func.apply_best_config(results)
my_func("hello")  # Works - get_config() returns the applied config
```

`OptimizationStateError` has `current_state` and `expected_states` attributes for diagnostics.

### ProviderValidationError

**When raised**: API key validation fails before optimization starts. Extends ConfigurationError.

```
traigent.utils.exceptions.ProviderValidationError: Provider validation failed:
  - openai: InvalidAPIKey
  - anthropic: MissingAPIKey
```

**Fixes**:

```bash
# Set the correct API keys
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

```bash
# Skip provider validation (if you know keys are valid but validation is failing)
export TRAIGENT_SKIP_PROVIDER_VALIDATION=true
```

Provider validation is controlled by the `TRAIGENT_SKIP_PROVIDER_VALIDATION`
environment variable, not a decorator argument (there is no `validate_providers`
keyword on `@traigent.optimize`).

The `failed_providers` attribute contains a list of `(provider, error_type)` tuples.

### Model 404 / Retired Provider Endpoint

**Symptom**: A trial fails with a `404` / "model not found" / "no such model" error from the
provider, or a run *degrades* — one or more trials silently fail or report `$0.00` cost (the ID
isn't in the pricing table) while others succeed. The function and config are fine; the **model
ID is stale**. Provider catalogs change: IDs get delisted, renamed, or quietly re-routed to a
retired backend. Two IDs we have seen go dead: `openrouter/google/gemini-flash-1.5-8b`
(delisted → 404) and `openrouter/anthropic/claude-3.5-haiku` (routes to a retired Bedrock
endpoint → degraded run).

**Fix**: verify the ID against the provider's *live* catalog, then swap any dead ID for a
verified live one:

```bash
# SDK-native preflight (no spend): valid -> true/false against the provider's known models
traigent models --provider openai
traigent models --provider anthropic --check claude-3-haiku-20240307
```

```bash
# Or query the provider's live catalog directly (e.g. OpenRouter, not covered by `traigent models`)
curl -s https://openrouter.ai/api/v1/models | grep -o '"id":"[^"]*"' | sort
```

Prefer a specific versioned ID (e.g. `claude-3-haiku-20240307`) over a moving `-latest` alias —
versioned IDs price reliably; an alias can resolve to a model whose pricing isn't recognized yet,
leaving cost untracked. The `traigent-integrations` skill's
[Verifying model availability](../traigent-integrations/references/litellm.md#verifying-model-availability)
section has the full per-provider check list.

### InvocationError

**When raised**: The decorated function raised an exception during a trial.

```
traigent.utils.exceptions.InvocationError: Function 'classify' failed with config {'model': 'gpt-4o'}
```

Has `config`, `input_data`, and `original_error` attributes. Check the original error:

```python
from traigent.utils.exceptions import InvocationError

try:
    results = func.optimize_sync()
except InvocationError as e:
    print(f"Config that caused failure: {e.config}")
    print(f"Original error: {e.original_error}")
```

### EvaluationError

**When raised**: The evaluator function failed when scoring a trial's output.

```
traigent.utils.exceptions.EvaluationError: Evaluator raised exception for config {'model': 'gpt-4o'}
```

Check your evaluator function handles edge cases (empty output, None, unexpected formats).

### Session-create fails with `400 VALIDATION_ERROR` / `429 quota_exceeded`

**When raised**: A cloud/hybrid run is rejected at session-create because a **plan quota** —
most often `optimization_samples` — has no headroom. Optimization is metered per billing
period along two dimensions: `optimization_samples` (examples evaluated; the usual binding
one) and `optimization_trials` (one session = one trial). A run is admitted only if
`current_usage + (max_trials × dataset_size)` stays under the `optimization_samples` limit;
on the free/hobby tier that limit is small (500), so a few runs can exhaust it and then
**every new run is blocked (0 trials)** until the monthly reset.

The backend's canonical signal is HTTP **429** with `error_code: "quota_exceeded"`, carrying
`resource_type`, `current_usage`, `limit`, and `reset_at`.

**Fixes**:

- Check your remaining quota and the reset date on the portal billing/usage page (or your
  plan's usage summary) before retrying.
- Size the next run to fit: lower `max_trials`, use a smaller eval dataset, or wait for the
  monthly reset. See the `traigent-run-optimization` skill ("Quota & Run Sizing").
- Upgrade the plan if you consistently need more `optimization_samples` headroom.

**Current SDK behavior (as of SDK 0.16.0 — may change):**

- A quota block can **surface as a generic `400 VALIDATION_ERROR`** on session-create rather
  than a clean 429, so a run that "looks like bad input" may actually be a quota block. If
  session-create fails right at the start of a cloud run, check quota before assuming the
  config or dataset is malformed.
- **Offline / mock dry-runs currently consume `optimization_samples` quota too** — a small
  (~12-example) dry-run was observed to burn ~32 samples. So a dry-run is not "free" against
  quota: either check your remaining headroom first, or budget for the dry-run itself when
  you are near the ceiling. (This is a current implementation detail, not a guarantee.)

### FeatureNotAvailableError

**When raised**: A feature requires an uninstalled plugin or optional dependency.

```
traigent.utils.exceptions.FeatureNotAvailableError: Feature 'LangChain integration' is not available.
  Requires the 'traigent-langchain' plugin. Install with: pip install traigent[integrations]
```

**Fix**: Install the indicated package.

### ModuleNotFoundError (Python)

**When raised**: Missing optional dependencies.

```
ModuleNotFoundError: No module named 'langchain_openai'
```

**Fix**:

```bash
# Install with specific extras
pip install traigent[integrations]    # LangChain, LiteLLM support
pip install traigent[all]             # Everything
pip install traigent[dev]             # Development tools
```

## Mock Mode

<!-- PROTECTED -->
Test your optimization setup without making real API calls or connecting to the backend. The recommended activation is in-code (production-blocked, visible in code review); the env-var path below remains as a legacy fallback that works in non-production.
<!-- /PROTECTED -->

**Recommended (in-code):**

```python
import traigent
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()  # raises in production
```

**Legacy fallback (env-var, dev/test only):**

```bash
# Mock LLM responses (no API keys needed) — hard-blocked in production
export TRAIGENT_MOCK_LLM=true
```

```python
import os
os.environ["TRAIGENT_MOCK_LLM"] = "true"

import traigent

@traigent.optimize(
    eval_dataset="test_data.jsonl",
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"], "temperature": [0.0, 0.5]},
    objectives=["accuracy"],
    max_trials=5,
    offline=True,
)
def my_func(text):
    config = traigent.get_config()
    # LLM calls return mock responses
    return "mock response"

# Runs without API keys, provider calls, or backend egress
results = my_func.optimize_sync()
```

Mock mode is essential for:
- CI/CD pipelines
- Unit testing
- Validating configuration space setup
- Testing evaluator logic

See [Mock Mode reference](references/mock-mode.md) for details.

## Troubleshooting Decision Tree

### No trials ran

1. Check dataset: does the file exist and contain valid JSONL?
2. Check configuration space: is it non-empty with valid lists?
3. Check for ConfigurationError in output
4. Enable `TRAIGENT_LOG_LEVEL=DEBUG` and check for early failures

### All trials failed

1. Check API keys: are they set and valid?
2. Check `results.failed_trials` for error messages:
   ```python
   for trial in results.failed_trials:
       print(f"{trial.trial_id}: {trial.error_message}")
   ```
3. Test your function standalone (outside optimization) with a sample config
4. Check provider status pages for outages
5. Check for a stale/dead model ID (404 or `$0.00` unpriced trials) — verify with `traigent models --provider <p> --check <id>` and swap any delisted/renamed ID (see "Model 404 / Retired Provider Endpoint" above)

### Wrong results (low scores)

1. Check your evaluator: does it correctly score good vs bad outputs?
2. Check your dataset: are expected outputs correct?
3. Check configuration space: does it include good model/parameter combinations?
4. Check `results.best_metrics` and compare with manual testing
5. Look at individual trial scores:
   ```python
   for trial in results.successful_trials:
       print(f"{trial.config} -> {trial.metrics}")
   ```

### Cost too high

1. Reduce `max_trials` to limit total API calls
2. Set a `cost_limit` on the decorator
3. Use cheaper models in the configuration space (e.g., `gpt-4o-mini` instead of `gpt-4o`)
4. Reduce dataset size for initial exploration
5. Check `results.experiment_stats.cost_per_configuration` to identify expensive configs

### Optimization is slow

1. Check trial durations: `results.experiment_stats.average_trial_duration`
2. Reduce dataset size for faster feedback
3. Set a `timeout` on the run call (`func.optimize_sync(timeout=30)` / `await func.optimize(timeout=30)`) — it is not a decorator argument
4. Use smaller models for initial exploration
5. Reduce `max_trials` or configuration space size

## Environment Verification

Verify your Traigent installation and environment:

```bash
# Check Traigent version and configuration
traigent info

# Validate a dataset file
traigent validate dataset.jsonl
```

From Python:

```python
import traigent
print(traigent.__version__)

# Check common diagnostic environment settings
import os
print(f"Mock LLM: {os.getenv('TRAIGENT_MOCK_LLM', 'false')}")
print(f"Log level: {os.getenv('TRAIGENT_LOG_LEVEL', 'INFO')}")
```

## Graceful Fallback Pattern

When optimization might fail, use a try/except pattern with a known-good default:

```python
import traigent
from traigent.utils.exceptions import TraigentError, CostLimitExceeded

DEFAULT_CONFIG = {"model": "gpt-4o-mini", "temperature": 0.0}

@traigent.optimize(
    eval_dataset="eval_data.jsonl",
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3, 0.7],
    },
    objectives=["accuracy"],
    max_trials=10,
)
def classify(text):
    config = traigent.get_config()
    # ... LLM call ...
    return result

# Attempt optimization with fallback
try:
    results = classify.optimize_sync()

    if results.best_score is not None and results.best_score >= 0.7:
        classify.apply_best_config(results)
        print(f"Applied optimized config: {results.best_config}")
    else:
        print(f"Score {results.best_score} too low, using default config")

except CostLimitExceeded as e:
    print(f"Budget exceeded (${e.accumulated:.2f}/${e.limit:.2f}), using default config")

except TraigentError as e:
    print(f"Optimization failed: {e.message}, using default config")

# The function still works with either applied or default config
```

This pattern ensures your application remains functional even when optimization encounters problems.

## Reference Files

- [Complete Error Reference](references/error-reference.md)
- [Mock Mode Details](references/mock-mode.md)
- [Logging Configuration](references/logging-config.md)

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
