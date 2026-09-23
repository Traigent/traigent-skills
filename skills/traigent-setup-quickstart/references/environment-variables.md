# Traigent Environment Variables

Common environment variables for Traigent quickstart workflows.

## Environment Variables Table

| Variable                           | Default         | Description                                                                                         |
| ---------------------------------- | --------------- | --------------------------------------------------------------------------------------------------- |
| `TRAIGENT_MOCK_LLM`               | `false`         | **Legacy** — when `true`, mocks all LLM API calls. Honored only outside production; **hard-blocked when `ENVIRONMENT=production`** (raises `OSError` at the first decoration, `optimize()` or CLI use, not at import). Prefer the in-code API `traigent.testing.enable_mock_mode_for_quickstart()` for new code. |
| `TRAIGENT_RUN_COST_LIMIT`         | `2.0`           | Maximum cost budget (in USD) per optimization run. Optimization stops when this limit is reached.    |
| `TRAIGENT_COST_APPROVED`          | `false`         | When `true`, skips the SDK's pre-run cost handshake (which fires only when the estimate exceeds `TRAIGENT_RUN_COST_LIMIT` or a model is unpriced) and downgrades the unpriced-model refusal to a warning. Set it per approved process, never as a standing export. |
| `TRAIGENT_SKIP_PROVIDER_VALIDATION`| `false`        | Gates only your own call to `traigent.providers.validate_providers`; the SDK runs no automatic provider validation at decoration time. |
| `TRAIGENT_OFFLINE_MODE`           | `false`         | When `true` (alias `TRAIGENT_OFFLINE`), zero backend egress: no session, no portal rows. Read live when the decorator and the run resolve it, so set it before the decorated function is defined. |
| `LITELLM_LOCAL_MODEL_COST_MAP`    | unset (Traigent sets it only when its cost module loads) | Set `LITELLM_LOCAL_MODEL_COST_MAP=True` in the environment, or in `os.environ` before any import, whenever your script imports `litellm` itself — otherwise LiteLLM downloads its pricing map from GitHub on import, even with `offline=True`. Set it to `false` to opt into the remote map. |
| `TRAIGENT_REQUIRE_CLOUD`          | (unset)         | When `1`, a connected run fails before any trial if the backend session cannot be created, instead of silently falling back to a local random search. |
| `TRAIGENT_LOG_EXAMPLE_CONTENT`    | `true`          | The SDK writes per-example prompt/response/expected text to its local run logs by default; set to `false` to keep ids and metrics only. |
| `TRAIGENT_BACKEND_URL`            | `https://portal.traigent.ai` | Backend the SDK talks to. Set only for a dev or self-hosted backend; a key issued by one backend is a 401 on another. |
| `TRAIGENT_DATASET_ROOT`           | (cwd)           | Directory every `eval_dataset` path must sit under (offline runs included); a path elsewhere is rejected when the run loads the dataset. |
| `TRAIGENT_VALIDATION_TIMEOUT`     | `5.0`           | Timeout in seconds for provider API key validation checks.                                          |
| `TRAIGENT_STRICT_COST_ACCOUNTING` | `false`         | When `true`, enables strict cost tracking. Cost overruns raise errors instead of warnings.          |
| `TRAIGENT_LOG_LEVEL`              | `INFO`          | Logging verbosity. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
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
| `GOOGLE_API_KEY`      | Google — read **first** by LiteLLM for `gemini/*` models (and by the google-genai SDK); an unrelated `GOOGLE_API_KEY` in the shell wins over `GEMINI_API_KEY` |
| `GEMINI_API_KEY`      | Google (Gemini via LiteLLM `gemini/*` models) — read only when `GOOGLE_API_KEY` is unset; `PALM_API_KEY` is also accepted |
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
export LITELLM_LOCAL_MODEL_COST_MAP=True   # no pricing-map download when your script imports litellm
export TRAIGENT_LOG_LEVEL=DEBUG
python my_optimization.py
```

### CI/CD Pipeline

CI environments typically already have a conftest or fixture that calls `enable_mock_mode_for_quickstart()`. The legacy `TRAIGENT_MOCK_LLM=true` env var still works in CI (`ENVIRONMENT` is normally not `production` in CI), but the in-code path is preferred.

```bash
export TRAIGENT_RUN_APPROVED=1            # CI approval gate: GitHub Actions requires it even for mock/offline runs
export TRAIGENT_SKIP_PROVIDER_VALIDATION=true
pytest tests/
```

### Production with Cost Controls

```bash
export OPENAI_API_KEY=sk-...
export TRAIGENT_RUN_COST_LIMIT=5.0        # the figure the user approved for this run
export TRAIGENT_STRICT_COST_ACCOUNTING=true
export TRAIGENT_LOG_LEVEL=WARNING
python optimize_production.py
# TRAIGENT_COST_APPROVED is deliberately not exported here: set it only in the
# process of a run whose estimate the user has already seen and approved.
```

### Debug Mode

```bash
export TRAIGENT_LOG_LEVEL=DEBUG
export TRAIGENT_DEBUG=1
python my_optimization.py
```

## .env File Support

The SDK does not load your project's `.env`: at import it looks only for a `.env` beside its own installed package. `python-dotenv` ships with `litellm` (a core dependency), so load the file yourself at the top of the script — `from dotenv import load_dotenv; load_dotenv()` — rather than relying on `litellm`'s own import-time lookup, which searches upward from wherever the venv sits.

Example `.env` file:

```
TRAIGENT_API_KEY=sk_...
OPENAI_API_KEY=sk-...
TRAIGENT_LOG_LEVEL=DEBUG
```
