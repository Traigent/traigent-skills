# Logging Configuration Reference

## Overview

Traigent uses Python's standard `logging` module. Verbosity is set in code with `traigent.configure(logging_level=...)`, and two environment variables adjust it:

| Variable | Purpose | Values |
|---|---|---|
| `TRAIGENT_LOG_LEVEL` | Level for Traigent loggers, applied only when `traigent.configure(logging_level=...)`, `traigent.initialize()` or the `traigent` CLI sets up logging (it overrides the level they are given) | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `TRAIGENT_DEBUG` | Enable full tracebacks for ConfigurationError | `1` (enabled), unset (disabled) |

## TRAIGENT_LOG_LEVEL

Controls the verbosity of Traigent's internal logging.

### Setting

```python
import traigent

traigent.configure(logging_level="DEBUG")  # before defining/running the optimization
```

`@traigent.optimize` and `optimize_sync()` do not set up logging themselves. The level
(from `TRAIGENT_LOG_LEVEL` when set, otherwise the one passed in) is applied only by
`traigent.configure(logging_level=...)`, `traigent.initialize()` and the `traigent` CLI.
In a script that only uses the decorator, `export TRAIGENT_LOG_LEVEL=DEBUG` changes
LiteLLM's verbosity but leaves the `traigent` loggers at Python's default (WARNING).

```bash
# Takes effect in a script that calls traigent.configure(logging_level=...);
# the environment value then overrides the level passed in code.
TRAIGENT_LOG_LEVEL=DEBUG python my_script.py
```

`configure()` replaces the ROOT logger's handlers. A host application with its own
logging setup should use the scoped snippet under "Programmatic Logging Configuration".

### Log Levels

| Level | What It Shows |
|---|---|
| `DEBUG` | Everything: config sampling, trial start/stop, metric extraction, cost tracking, backend communication, internal state changes. Very verbose. |
| `INFO` | Optimization lifecycle events: run start, trial completion, best config updates, run completion. The level `traigent.initialize()` uses when none is configured. A decorated run that never calls `configure()` stays at Python's default, WARNING, so INFO lines do not appear. |
| `WARNING` | Non-fatal issues: deprecated API usage, non-numeric metric values, retry attempts, fallback behavior. |
| `ERROR` | Trial failures, evaluation errors, provider errors, unrecoverable issues within a trial. |
| `CRITICAL` | Fatal errors that prevent the optimization from continuing at all. Rare. |

### What Each Level Shows

#### DEBUG

```
DEBUG traigent.core.orchestrator: Sampling configuration: {'model': 'gpt-4o-mini', 'temperature': 0.3}
DEBUG traigent.core.trial_lifecycle: Starting trial trial-001 with config {'model': 'gpt-4o-mini', 'temperature': 0.3}
DEBUG traigent.core.trial_lifecycle: Trial trial-001 function returned in 2.3s
DEBUG traigent.core.trial_lifecycle: Trial trial-001 metrics: {'accuracy': 0.85}
DEBUG traigent.core.cost_enforcement: Trial trial-001 cost: $0.0012, total: $0.0012
DEBUG traigent.core.orchestrator: Trial trial-001 completed, score=0.85 (best so far)
```

Use DEBUG when:
- Investigating why a specific trial failed
- Understanding configuration sampling behavior
- Debugging metric extraction issues
- Tracing cost tracking calculations
- Diagnosing backend communication problems

#### INFO

```
INFO traigent.core.orchestrator: Starting optimization with max_trials=10
INFO traigent.core.orchestrator: Trial 1/10 completed: score=0.85
INFO traigent.core.orchestrator: Trial 2/10 completed: score=0.72
INFO traigent.core.orchestrator: New best score: 0.92 with config {'model': 'gpt-4o', 'temperature': 0.0}
INFO traigent.core.orchestrator: Optimization completed: best_score=0.92, duration=45.3s
```

Use INFO for:
- Normal operation monitoring
- Tracking optimization progress
- Production logging

#### WARNING

```
WARNING traigent.core.trial_lifecycle: Non-numeric metric value for 'model_name': 'gpt-4o' (use metadata instead)
WARNING traigent.utils.exceptions: ConfigAccessWarning: Use traigent.get_config() instead of get_current_config()
WARNING traigent.core.cost_enforcement: Cost approaching limit: $0.45/$0.50
```

#### ERROR

```
ERROR traigent.core.trial_lifecycle: Trial trial-003 failed: APIError: Rate limit exceeded
ERROR traigent.core.orchestrator: All trials failed, no valid results
```

## TRAIGENT_DEBUG

This variable controls traceback display for `ConfigurationError` specifically.

### Default Behavior (TRAIGENT_DEBUG not set)

ConfigurationError shows a clean, single-line message:

```
traigent.utils.exceptions.ConfigurationError: algorithm='bayesian' requires managed optimization and cannot be used with offline=True or TRAIGENT_OFFLINE=1.
```

(Raised at decoration by `@traigent.optimize(..., offline=True, algorithm="bayesian")`.)

### With TRAIGENT_DEBUG=1

Full Python traceback is shown:

```
Traceback (most recent call last):
  File "my_script.py", line 2, in <module>
    @traigent.optimize(eval_dataset="eval_data.jsonl", configuration_space={"model": ["a", "b"]}, offline=True, algorithm="bayesian")
  File "/path/to/traigent/api/decorators.py", line 3088, in optimize
    execution_policy = _resolve_execution_policy_from_options(
  File "/path/to/traigent/api/decorators.py", line 1687, in _resolve_execution_policy_from_options
    return resolve_execution_policy(
  File "/path/to/traigent/config/types.py", line 550, in resolve_execution_policy
    raise ConfigurationError(
traigent.utils.exceptions.ConfigurationError: algorithm='bayesian' requires managed optimization and cannot be used with offline=True or TRAIGENT_OFFLINE=1.
```

Line numbers vary by SDK version. A non-list or empty `configuration_space` is not a
`ConfigurationError` (see [Error Reference](error-reference.md)).

```bash
# Enable
export TRAIGENT_DEBUG=1

# Disable
unset TRAIGENT_DEBUG
```

This only affects `ConfigurationError` and its subclasses. All other exceptions always show full tracebacks.

## Combining Logging Options

For maximum diagnostic information:

```bash
# my_script.py calls traigent.configure(logging_level="DEBUG") before the run
export TRAIGENT_DEBUG=1
python my_script.py
```

For production with minimal noise:

```bash
export TRAIGENT_LOG_LEVEL=WARNING
# TRAIGENT_DEBUG unset
python my_script.py
```

## Programmatic Logging Configuration

You can also configure Traigent's logger directly. This works on a decorated run and leaves
the host application's root logging untouched:

```python
import logging

# Get the Traigent root logger
traigent_logger = logging.getLogger("traigent")
traigent_logger.setLevel(logging.DEBUG)

# Add a file handler for Traigent logs
handler = logging.FileHandler("traigent_debug.log")
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
traigent_logger.addHandler(handler)
```

## Logging in Tests

For pytest, control logging with standard pytest options:

```bash
# Show Traigent debug logs during test runs
TRAIGENT_LOG_LEVEL=DEBUG pytest tests/ -s --log-cli-level=DEBUG

# Capture logs in test output
pytest tests/ --log-level=DEBUG
```

Or in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
log_cli = true
log_cli_level = "INFO"
```
