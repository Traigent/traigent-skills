# Traigent Exception Reference

## Exception Hierarchy

```
Exception
  +-- TraigentError (base for all Traigent exceptions)
  |     +-- ConfigurationError
  |     |     +-- ProviderValidationError
  |     |     +-- ConfigurationSpaceError
  |     +-- ValidationError
  |     |     +-- TraigentValidationError
  |     |     +-- TVLValidationError
  |     |     |     +-- TVLConstraintError
  |     |     +-- DatasetValidationError
  |     |     +-- ObjectiveValidationError
  |     |     +-- JWTValidationError
  |     +-- InvocationError
  |     +-- EvaluationError
  |     +-- OptimizationError
  |     |     +-- CostLimitExceeded
  |     +-- OptimizationStateError
  |     +-- FeatureNotAvailableError
  |     +-- DataIntegrityError
  |     |     +-- MetricExtractionError
  |     |     +-- DTOSerializationError
  |     +-- ClientError
  |     |     +-- StandardizedClientError
  |     +-- AuthenticationError
  |     +-- ServiceError
  |     |     +-- TraigentConnectionError
  |     |     +-- ServiceUnavailableError
  |     |     +-- QuotaExceededError
  |     |     +-- InsufficientFundsError
  |     +-- VendorPauseError
  |     +-- SessionError
  |     +-- AgentExecutionError
  |     +-- PlatformCapabilityError
  |     +-- StorageError
  |     |     +-- TraigentStorageError
  |     +-- PluginError
  |     |     +-- PluginVersionError
  |     +-- RetryableError
  |     |     +-- RateLimitError
  |     |     +-- NetworkError
  |     +-- NonRetryableError
  |     +-- RetryError
  |     +-- TraigentTimeoutError
  |     +-- TrialPrunedError
  +-- UserWarning
        +-- TraigentWarning
              +-- ConfigAccessWarning
              +-- TraigentDeprecationWarning
```

## Exceptions Users Commonly Encounter

### TraigentError

**Base exception for all Traigent errors.**

| Attribute | Type | Description |
|---|---|---|
| `message` | `str` | Human-readable error message. |
| `details` | `dict[str, Any]` | Additional error context. Default: `{}`. |

```python
from traigent.utils.exceptions import TraigentError

try:
    results = func.optimize_sync()
except TraigentError as e:
    print(f"Error: {e.message}")
    print(f"Details: {e.details}")
```

### ConfigurationError

**Invalid or malformed configuration.**

Raised when configuration values are invalid, features are unsupported, or required configuration is missing. Set `TRAIGENT_DEBUG=1` for full tracebacks.

| Inherited from | TraigentError |
|---|---|
| `message` | Error description |
| `details` | Additional context |

**Common triggers**:
- A named smart algorithm with local execution (`offline=True, algorithm="bayesian"`)
- Invalid parameter names
- Unsupported `algorithm` value or invalid `offline` setting

Not `ConfigurationError`: a non-list `configuration_space` value raises `ValidationError`, and an
empty `configuration_space` raises a builtin `ValueError`. Catch `ValidationError`/`TraigentError`
or `ValueError` for those.

**Resolution**: Check the error message and fix the configuration. Use `TRAIGENT_DEBUG=1` for the full traceback.

### ProviderValidationError

**API key validation failure — opt-in, never raised by the SDK on its own.**

`@traigent.optimize` runs no automatic provider validation, so nothing in the SDK raises this.
It exists for you to raise from your own pre-run check: call
`validate_providers(...)` (`from traigent.providers import validate_providers` — a plain
`import traigent` does not expose the submodule), inspect the results, and raise
`ProviderValidationError` yourself if you want a hard failure before any paid trial.

| Attribute | Type | Description |
|---|---|---|
| `message` | `str` | Error description with all failed providers. |
| `failed_providers` | `list[tuple[str, str]]` | List of `(provider_name, error_type)` tuples. |
| `details` | `dict[str, Any]` | Additional context. |

**Resolution**:
1. Set correct API keys in environment variables
2. Or let your own pre-run check honour `TRAIGENT_SKIP_PROVIDER_VALIDATION`. Setting it switches nothing off on its own: `validate_providers()` does not read it and the decorator never validates keys. Branch on `traigent.utils.env_config.skip_provider_validation()` before calling (there is no `validate_providers` decorator argument)

### CostLimitExceeded

**Pre-run cost approval declined** — raised before the first trial when the estimate exceeds the
limit and no approval is present. A mid-run budget hit does not raise: the run returns a partial
result with `stop_reason == "cost_limit"`. Subclass of `OptimizationError`.

| Attribute | Type | Description |
|---|---|---|
| `estimated` | `float \| None` | The pre-run estimate that exceeded the limit (USD). |
| `limit` | `float` | The configured cost limit (USD). |
| `accumulated` | `float` | Cost spent (USD) — `0.0` on the pre-run decline. |

```python
from traigent.utils.exceptions import CostLimitExceeded

try:
    results = func.optimize_sync()
except CostLimitExceeded as e:
    print(f"Refused before spending: estimated ${e.estimated or 0:.2f} > ${e.limit:.2f}")
    raise
if results.stop_reason == "cost_limit":
    print("Budget reached mid-run — partial result, paid trials kept")
```

A `stop_reason == "cost_limit"` whose stop message says `per-trial cost unknown: fallback trial
limit` is not a dollar cap: cost was not measured. Raising `cost_limit` does not help — see
"Run stopped because cost was not measured" in `SKILL.md`.

**Resolution**: take the estimate back to the user for an explicit approval of a stated ceiling,
or shrink the run (cheaper models, fewer `max_trials`). Never set `TRAIGENT_COST_APPROVED=true`
persistently to make the decline go away.

### InsufficientFundsError

**The LLM provider account has no credit (HTTP 402 / billing error).** Subclass of
`ServiceError`; non-retryable — the account must be topped up. Non-interactively the run ends with
`results.stop_reason == "vendor_error"` and the paid trials kept; do not retry blindly.

### OptimizationStateError

**Invalid lifecycle state for the requested operation.**

| Attribute | Type | Description |
|---|---|---|
| `message` | `str` | What went wrong and what state is needed. |
| `current_state` | `str \| None` | The current lifecycle state. |
| `expected_states` | `list[str]` | States that would make this operation valid. |

**Common triggers**:
- Calling `traigent.get_config()` with no active trial and no applied config
- Calling `get_trial_config()` outside of an optimization trial
- Operations that require a specific lifecycle state

**Resolution**: Either run optimization first, or call `apply_best_config()` before using the function.

### InvocationError

**Raised only on explicit paths, not for ordinary function exceptions.** The local evaluator converts an ordinary exception in your function into a per-example failure (`Function call failed: ...`) and keeps going, so a run with no `InvocationError` can still have many failed examples; check scored-example coverage.

| Attribute | Type | Description |
|---|---|---|
| `message` | `str` | Error description. |
| `config` | `dict[str, Any] \| None` | The configuration that caused the failure. |
| `input_data` | `dict[str, Any] \| None` | The input data that was passed. |
| `original_error` | `Exception \| None` | The underlying exception from the user function. |

**Resolution**: Check `original_error` to see what actually failed inside your function.

### EvaluationError

**Evaluator function failed when scoring output.**

| Attribute | Type | Description |
|---|---|---|
| `message` | `str` | Error description. |
| `config` | `dict[str, Any] \| None` | The configuration being evaluated. |
| `original_error` | `Exception \| None` | The underlying evaluator exception. |

**Resolution**: Ensure your evaluator handles edge cases (None, empty strings, unexpected output formats).

### ValidationError

**Input validation failure.**

Base class for validation-related errors. Subclasses include:
- `DatasetValidationError` - invalid dataset format
- `ObjectiveValidationError` - invalid objective specification
- `TraigentValidationError` - general validation with suggestions

### FeatureNotAvailableError

**Missing plugin or optional dependency.**

| Attribute | Type | Description |
|---|---|---|
| `feature_name` | `str` | Name of the requested feature. |
| `plugin_name` | `str \| None` | Required plugin name. |
| `install_hint` | `str \| None` | pip install command to fix. |

**Resolution**: Run the `install_hint` command (e.g., `pip install "traigent[integrations]>=0.24.0"`).

### DataIntegrityError

**Data corruption or invalid conversion detected.**

| Attribute | Type | Description |
|---|---|---|
| `message` | `str` | Error description. |
| `field` | `str \| None` | Field that failed validation. |
| `value` | `Any` | The invalid value. |

Subclass `MetricExtractionError` adds `trial_id`, `example_id`, and `original_error`.

### ServiceError

**Remote service communication failure.**

| Attribute | Type | Description |
|---|---|---|
| `service_name` | `str \| None` | Name of the service. |
| `endpoint` | `str \| None` | API endpoint that failed. |
| `status_code` | `int \| None` | HTTP status code. |

Subclasses: `TraigentConnectionError`, `ServiceUnavailableError`, `QuotaExceededError`.

### RateLimitError

**Provider rate limit exceeded.**

| Attribute | Type | Description |
|---|---|---|
| `retry_after` | `float \| None` | Suggested wait time in seconds. |

Traigent handles retries automatically for retryable errors. This surfaces when retries are exhausted.

## Catching Exceptions

### Catch all Traigent errors

```python
from traigent.utils.exceptions import TraigentError

try:
    results = func.optimize_sync()
except TraigentError as e:
    print(f"Traigent error: {e.message}")
```

### Catch specific errors

```python
from traigent.utils.exceptions import (
    CostLimitExceeded,
    ConfigurationError,
    ProviderValidationError,
    OptimizationStateError,
)

try:
    results = func.optimize_sync()
except CostLimitExceeded as e:
    print(f"Pre-run estimate ${e.estimated} exceeds the ${e.limit:.2f} limit — approve or lower it")
except ProviderValidationError as e:
    # Only reachable if YOUR pre-run validate_providers() check raises it;
    # the SDK never raises this itself (see the entry above).
    print(f"Bad API keys: {e.failed_providers}")
except ConfigurationError as e:
    print(f"Config problem: {e.message}")
except OptimizationStateError as e:
    print(f"Wrong state: {e.current_state}, need: {e.expected_states}")
```

## Warnings

Traigent also issues warnings (non-fatal) for deprecated patterns:

| Warning | Meaning |
|---|---|
| `ConfigAccessWarning` | Using deprecated config access method. Use `traigent.get_config()` instead. |
| `TraigentDeprecationWarning` | A deprecated feature is being used. |
