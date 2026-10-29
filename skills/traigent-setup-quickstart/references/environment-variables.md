# Traigent Environment Variables

Common environment variables for Traigent quickstart workflows.

## Environment Variables Table

| Variable                           | Default         | Description                                                                                         |
| ---------------------------------- | --------------- | --------------------------------------------------------------------------------------------------- |
| `TRAIGENT_MOCK_LLM`               | `false`         | **Deprecated** (DeprecationWarning on traigent 0.27.0, hidden by default; "will be removed in a future release") — when `true`, mocks all LLM API calls. Honored only outside production; **hard-blocked when `ENVIRONMENT=production`** (raises `OSError` at the first decoration, `optimize()` or CLI use, not at import). Prefer the in-code API `traigent.testing.enable_mock_mode_for_quickstart()` for new code. |
| `TRAIGENT_RUN_COST_LIMIT`         | `2.0`           | Maximum cost budget (in USD) per optimization run. Optimization stops when this limit is reached — for measured cost only; calls Traigent cannot measure are still billed (see `run-cost-and-limits.md`). |
| `TRAIGENT_FALLBACK_TRIAL_LIMIT`   | `10`            | SDK 0.30.0+. Trial cap for a run whose cost cannot be measured and that did not set `max_trials`/`max_total_examples` explicitly; the run stops at this many trials with warning `COST_UNMEASURED_TRIAL_LIMIT_REACHED` (see `run-cost-and-limits.md`). |
| `TRAIGENT_COST_APPROVED`          | `false`         | When `true`, skips the SDK's pre-run cost handshake (which fires only when the estimate exceeds `TRAIGENT_RUN_COST_LIMIT` or a model is unpriced) and downgrades the unpriced-model refusal to a warning. Set it per approved process, never as a standing export. |
| `TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT` | (unset) | SDK 0.31.0+. Test and walkthrough use only: skips the pre-run cost estimate for a **mock** run, and only when mock mode is on and `ENVIRONMENT` (or `TRAIGENT_ENV` / `TRAIGENT_ENVIRONMENT`) is explicitly one of `dev`, `development`, `local`, `test`, `testing`, `stage`, `staging`. Ignored when the environment is unset, `ci` or production. Prefer a small dataset slice; never use `TRAIGENT_COST_APPROVED` to get a mock run past the estimate. |
| `TRAIGENT_SKIP_PROVIDER_VALIDATION`| `false`        | Gates only your own call to `traigent.providers.validate_providers`; the SDK runs no automatic provider validation at decoration time. |
| `TRAIGENT_OFFLINE_MODE`           | `false`         | When `true` (alias `TRAIGENT_OFFLINE`), zero backend egress: no session, no portal rows. Read live when the decorator and the run resolve it, so set it before the decorated function is defined. |
| `LITELLM_LOCAL_MODEL_COST_MAP`    | unset (on traigent <= 0.28.0, Traigent sets it only when its cost module loads; SDK 0.29.0+ sets it as soon as `traigent` is imported) | Set `LITELLM_LOCAL_MODEL_COST_MAP=True` in the environment, or in `os.environ` before any import, whenever your script imports `litellm` itself — otherwise LiteLLM downloads its pricing map from GitHub on import, even with `offline=True`. On traigent <= 0.28.0 this is required; fixed in 0.29.0, provided `traigent` is imported before `litellm` (if `litellm` is imported first, even 0.29.0+ cannot stop its import-time fetch). Set it to `false` to opt into the remote map (or `TRAIGENT_LITELLM_LIVE_PRICES=1` on SDK 0.29.0+). |
| `TRAIGENT_REQUIRE_CLOUD`          | (unset)         | When `1`, a connected run fails before any trial if the backend session cannot be created, instead of silently falling back to a local random search. |
| `TRAIGENT_LOG_EXAMPLE_CONTENT`    | `true`          | The SDK writes per-example prompt/response/expected text to its local run logs by default; set to `false` to keep ids and metrics only. |
| `TRAIGENT_BACKEND_URL`            | `https://portal.traigent.ai` | Backend the SDK talks to. Set only for a dev or self-hosted backend; a key issued by one backend is a 401 on another. |
| `TRAIGENT_DATASET_ROOT`           | (cwd)           | Directory every `eval_dataset` path must sit under (offline runs included); a path elsewhere is rejected when the run loads the dataset. |
| `TRAIGENT_VALIDATION_TIMEOUT`     | `5.0`           | Timeout in seconds for provider API key validation checks — i.e. for your own `validate_providers(...)` call; the SDK runs none of its own. |
| `TRAIGENT_STRICT_COST_ACCOUNTING` | `false`, but see note | When `true`, fail fast (raise `CostTrackingRequiredError`) when a call's cost cannot be determined, instead of recording $0. It is **not** a budget guard — a budget overrun is governed by `TRAIGENT_RUN_COST_LIMIT`. **Unset is not the same as `false`:** a run whose `objectives` include `cost` turns strict accounting on for itself, so an unpriced model raises there even with the variable unset. An explicit value always wins. |
| `TRAIGENT_LOG_LEVEL`              | `INFO`          | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) for `traigent.configure(...)`, `traigent.initialize()` and the `traigent` CLI; when set it overrides the level they are given. It does **not** enable Traigent logs in a script that only uses `@traigent.optimize`. |
| `TRAIGENT_DEBUG`                  | (unset)         | When set to `1`, shows full tracebacks for `ConfigurationError` instead of user-friendly messages.  |
| `TRAIGENT_STRICT_VALIDATION`      | `true`          | When `true`, DTO schema validation raises exceptions. When `false`, logs warnings only.             |
| `ENVIRONMENT`                      | `development`   | Execution environment. Set to `production` for production deployments. Policy checks such as the mock-cost exemption treat an unset value as production, so set it explicitly (for example `development`) when such a check must see a non-production environment. |
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
export TRAIGENT_LOG_LEVEL=DEBUG            # applied only once configure()/initialize()/the CLI runs
python my_optimization.py
```

The script above uses `@traigent.optimize` only, so `TRAIGENT_LOG_LEVEL` alone changes LiteLLM's
verbosity, not Traigent's — see [Debug Mode](#debug-mode) for the call that turns Traigent's own
logs on.

### CI/CD Pipeline

CI environments typically already have a conftest or fixture that calls `enable_mock_mode_for_quickstart()`. The legacy `TRAIGENT_MOCK_LLM=true` env var still works in CI (`ENVIRONMENT` is normally not `production` in CI), but it is deprecated and will be removed in a future release — use the in-code path for new setups.

```bash
export TRAIGENT_RUN_APPROVED=1            # CI approval gate: GitHub Actions requires it even for mock/offline runs
pytest tests/
```

`TRAIGENT_SKIP_PROVIDER_VALIDATION` is not needed here: the SDK runs no provider validation of its
own, so there is nothing for it to skip. It is a signal your own pre-run check reads (via
`traigent.utils.env_config.skip_provider_validation()`); setting it does not stop
`validate_providers()` from running if your suite calls that directly.

### Production with Cost Controls

```bash
# OPENAI_API_KEY comes from the deployment's environment or secret store; locally, from
# .env via ".env File Support" below (load_dotenv() before the provider client is created).
export TRAIGENT_RUN_COST_LIMIT=5.0        # the figure the user approved for this run
export TRAIGENT_STRICT_COST_ACCOUNTING=true
export TRAIGENT_LOG_LEVEL=WARNING
python optimize_production.py
# TRAIGENT_COST_APPROVED is deliberately not exported here: set it only in the
# process of a run whose estimate the user has already seen and approved.
```

### Debug Mode

Neither variable turns on Traigent debug logs in a script that only uses
`@traigent.optimize`: `TRAIGENT_LOG_LEVEL` is applied by `traigent.configure(...)`,
`traigent.initialize()` and the `traigent` CLI, and `TRAIGENT_DEBUG=1` only shows raw
`ConfigurationError` tracebacks. Call `configure()` in the script to get the logs.

```python
import traigent

traigent.configure(logging_level="DEBUG")  # Traigent debug logs; note it reconfigures the ROOT logger
```

```bash
export TRAIGENT_LOG_LEVEL=DEBUG   # honoured by configure()/initialize()/the CLI
export TRAIGENT_DEBUG=1           # raw ConfigurationError tracebacks only
python my_optimization.py
```

## .env File Support

Load order on `traigent>=0.28.0`: variables already exported in the environment win, then your project's `.env` (found by walking up from the working directory to the nearest `.git`, `pyproject.toml`, `setup.cfg` or `setup.py`), then a `.env` beside the installed package; this happens at import time, when `traigent.utils.env_config` is first imported (importing `traigent.optimize` pulls it in before any decoration), and `TRAIGENT_SKIP_DOTENV=1` disables it only if set before that first import. On 0.24.0-0.27.0 only the `.env` beside the installed package is read. `python-dotenv` ships with `litellm` (a core dependency), so keep loading the file yourself at the top of the script — `from dotenv import load_dotenv; load_dotenv()` — which is required below 0.28.0 and harmless above it (it does not override existing values).

Before writing any key into `.env`, run the block under [Using a .env File](../SKILL.md#using-a-env-file) from the directory that will hold it and continue only if it exits 0. It adds the adjacent `.gitignore` rule, refuses an already tracked `.env`, and leaves the file at mode 0600. Never type a key into an `export` at a shell prompt.

Then fill the `.env` file in your editor:

```
TRAIGENT_API_KEY=sk_...
OPENAI_API_KEY=sk-...
TRAIGENT_LOG_LEVEL=DEBUG
```

`TRAIGENT_LOG_LEVEL` here is read by `traigent.configure(...)`, `traigent.initialize()` and the
`traigent` CLI — and when it is set it **overrides** the level passed to `configure()`. On its own,
in a script that only uses `@traigent.optimize`, it does not enable Traigent debug logs.
