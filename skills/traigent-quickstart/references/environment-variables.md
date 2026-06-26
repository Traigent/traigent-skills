# Traigent Environment Variables

Common environment variables for Traigent quickstart workflows.

## Environment Variables Table

| Variable                           | Default         | Description                                                                                         |
| ---------------------------------- | --------------- | --------------------------------------------------------------------------------------------------- |
| `TRAIGENT_MOCK_LLM`               | `false`         | **Legacy** — when `true`, mocks all LLM API calls. Honored only outside production; **hard-blocked when `ENVIRONMENT=production`** (raises `OSError` at import). Prefer the in-code API `traigent.testing.enable_mock_mode_for_quickstart()` for new code. |
| `TRAIGENT_RUN_COST_LIMIT`         | `2.0`           | Maximum cost budget (in USD) per optimization run. Optimization stops when this limit is reached.    |
| `TRAIGENT_COST_APPROVED`          | `false`         | When `true`, skips the interactive cost confirmation prompt before starting optimization.            |
| `TRAIGENT_SKIP_PROVIDER_VALIDATION`| `false`        | When `true`, skips API key validation at decoration time. Useful in CI environments.                |
| `TRAIGENT_VALIDATION_TIMEOUT`     | `5.0`           | Timeout in seconds for provider API key validation checks.                                          |
| `TRAIGENT_STRICT_COST_ACCOUNTING` | `false`         | When `true`, enables strict cost tracking. Cost overruns raise errors instead of warnings.          |
| `TRAIGENT_LOG_LEVEL`              | `INFO`          | Logging verbosity. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`.                                    (read on all current SDK versions) |
| `TRAIGENT_DEBUG`                  | (unset)         | When set to `1`, shows full tracebacks for `ConfigurationError` instead of user-friendly messages.  |
| `TRAIGENT_STRICT_VALIDATION`      | `true`          | When `true`, DTO schema validation raises exceptions. When `false`, logs warnings only.             |
| `ENVIRONMENT`                      | `development`   | Execution environment. Set to `production` for production deployments.                              |
| `JWT_SECRET_KEY`                   | (none)          | Secret key for JWT token validation. Required for production security features.                     |
| `TRAIGENT_API_KEY`                | (none)          | Authenticates the default cloud smart optimizer and portal result sync for non-offline runs. |

## LLM Provider API Keys

These are standard provider API keys consumed by the respective LLM SDKs. Traigent passes them through.

| Variable              | Provider                |
| --------------------- | ----------------------- |
| `OPENAI_API_KEY`      | OpenAI (GPT models)     |
| `ANTHROPIC_API_KEY`   | Anthropic (Claude models)|
| `GROQ_API_KEY`        | Groq (fast inference)   |
| `GOOGLE_API_KEY`      | Google (Gemini via google-genai SDK) |
| `GEMINI_API_KEY`      | Google (Gemini via LiteLLM `gemini/*` models) |
| `WANDB_API_KEY`       | Weights & Biases        |
| `MLFLOW_TRACKING_URI` | MLflow tracking server  |

## Usage Examples

### Local Development (No API Costs)

Recommended: in-code activation, env vars only for logging or cost controls.

```python
# my_optimization.py
from traigent.testing import enable_mock_mode_for_quickstart
enable_mock_mode_for_quickstart()
# ...
```

```bash
export TRAIGENT_LOG_LEVEL=DEBUG (read on all current SDK versions)
python my_optimization.py
```

### CI/CD Pipeline

CI environments typically already have a conftest or fixture that calls `enable_mock_mode_for_quickstart()`. The legacy `TRAIGENT_MOCK_LLM=true` env var still works in CI (`ENVIRONMENT` is normally not `production` in CI), but the in-code path is preferred.

```bash
export TRAIGENT_COST_APPROVED=true
export TRAIGENT_SKIP_PROVIDER_VALIDATION=true
pytest tests/
```

### Production with Cost Controls

```bash
export OPENAI_API_KEY=sk-...
export TRAIGENT_RUN_COST_LIMIT=5.0
export TRAIGENT_STRICT_COST_ACCOUNTING=true
export TRAIGENT_COST_APPROVED=true
export TRAIGENT_LOG_LEVEL=WARNING (read on all current SDK versions)
python optimize_production.py
```

### Debug Mode

```bash
export TRAIGENT_LOG_LEVEL=DEBUG (read on all current SDK versions)
export TRAIGENT_DEBUG=1
python my_optimization.py
```

## .env File Support

When `python-dotenv` is installed (included in the `integrations` extra), Traigent automatically loads variables from a `.env` file in the current working directory.

Example `.env` file:

```
TRAIGENT_API_KEY=sk_...
OPENAI_API_KEY=sk-...
TRAIGENT_LOG_LEVEL=DEBUG (read on all current SDK versions)
```
