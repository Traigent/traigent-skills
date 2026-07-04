# Traigent Installation Extras

Full reference of optional dependency groups available via `pip install 'traigent[extra_name]>=0.19'`.

## Extras Table

| Extra           | Description                                        | Key Packages                                                                 |
| --------------- | -------------------------------------------------- | ---------------------------------------------------------------------------- |
| `analytics`     | Analytics and intelligence features                | numpy, pandas, matplotlib                                                    |
| `bayesian`      | Bayesian optimization algorithms                   | scikit-learn, scipy                                                          |
| `integrations`  | Framework integrations                             | LangChain (+ community/anthropic/openai/google), OpenAI, Anthropic, Groq, Google GenAI, MLflow, W&B, python-dotenv, boto3, faiss-cpu |
| `dspy`          | DSPy prompt optimization                           | dspy-ai                                                                      |
| `pydanticai`    | PydanticAI agent framework                         | pydantic-ai                                                                  |
| `security`      | Enterprise security features                       | PyJWT, passlib, FastAPI, Starlette, uvicorn, redis, defusedxml, pyotp        |
| `visualization` | Visualization and plotting                         | matplotlib, plotly                                                           |
| `hybrid`        | External HTTP/MCP service integration helpers      | httpx with HTTP/2                                                            |
| `tracing`       | OpenTelemetry tracing                              | opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp            |
| `test`          | Testing dependencies                               | pytest, pytest-asyncio, pytest-cov, pytest-mock, pytest-timeout, pytest-xdist, coverage, ragas, rapidfuzz, hypothesis |
| `dev`           | Development tools (linting + testing)              | pytest suite, black, isort, flake8, mypy, pre-commit, ruff, bandit           |
| `docs`          | Documentation generation                           | mkdocs, mkdocs-material, mkdocstrings                                        |
| `ml`            | Machine learning bundle                            | bayesian + analytics + numpy + scipy                                         |
| `cloud`         | Cloud and portal integration dependencies          | security + boto3                                                             |
| `recommended`   | Core user-facing extras (primary install choice)   | integrations, analytics, visualization, hybrid, pydanticai                                    |
| `all`           | User-facing extras (excludes dev/docs/ml/cloud)    | analytics, integrations, pydanticai, security, visualization, test, tracing, hybrid           |
| `enterprise`    | Enterprise bundle with all production features     | analytics, integrations, security, visualization, test, tracing, ml, cloud, hybrid            |

## Install Commands

### pip

```bash
# Individual extras
pip install "traigent[analytics]>=0.19"
pip install "traigent[bayesian]>=0.19"
pip install "traigent[integrations]>=0.19"
pip install "traigent[dspy]>=0.19"
pip install "traigent[pydanticai]>=0.19"
pip install "traigent[security]>=0.19"
pip install "traigent[visualization]>=0.19"
pip install "traigent[hybrid]>=0.19"
pip install "traigent[tracing]>=0.19"
pip install "traigent[test]>=0.19"
pip install "traigent[dev]>=0.19"
pip install "traigent[docs]>=0.19"
pip install "traigent[ml]>=0.19"
pip install "traigent[cloud]>=0.19"

# Combined bundles
pip install "traigent[recommended]>=0.19"
pip install "traigent[all]>=0.19"
pip install "traigent[enterprise]>=0.19"

# Multiple extras at once
pip install "traigent[integrations,analytics,visualization]>=0.19"
```

## Core Dependencies (Always Installed)

The base `pip install "traigent>=0.19"` includes `litellm`, so keyless mock-mode
examples can intercept `litellm.completion(...)` without an integrations extra. It also
includes core SDK/runtime packages such as `pydantic`, `click`, and `httpx`.

The installed wheel is authoritative: run `pip show traigent` in the active environment
to see the exact dependency list for that version. Do not assume optional packages such
as `optuna`, `mcp`, or `claude-code-sdk` are present unless you installed an extra that
declares them.

## Notes

- Requires Python >= 3.11.
- `faiss-cpu` (in `integrations`) is not available on Windows.
- Algorithm selection is controlled by `algorithm`, not by extras: omit it for the default cloud smart optimizer, or use `grid`/`random` for local search. Named smart algorithms such as `bayesian`/`optuna` validate as known names but are **not yet executable**, locally or in the Traigent cloud (verified against SDK 0.19.x) — the `bayesian`/`ml` extras install their dependencies ahead of that roadmap work, not a usable algorithm today.
- `all` includes user-facing runtime extras only — it does **not** include `dev`, `docs`, `dspy`, `ml`, or `cloud`. Use `enterprise` for ml+cloud, or `recommended` as the primary install.
- `enterprise` includes `ml` and `cloud` on top of the runtime extras; `dev` and `docs` remain opt-in.
- The difference between `all` and `enterprise`: `enterprise` adds `ml` and `cloud`; `all` does not include `bayesian` as a top-level extra (it's pulled in transitively by `ml`).
