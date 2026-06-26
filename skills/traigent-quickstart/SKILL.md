---
name: traigent-quickstart
description: "Install and set up the Traigent SDK for LLM optimization. Use when the user wants to install traigent, set up their first optimization, create an evaluation dataset, or get started with @traigent.optimize. Covers pip install, API-key setup, mock mode, and running a first optimization."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.3"
---

# Traigent Quickstart

## When to Use

Use this skill when:

- Setting up Traigent for the first time in a new project
- Installing the SDK and configuring the environment
- Creating a first `@traigent.optimize` decorated function
- Building an evaluation dataset in JSONL format
- Verifying that the installation works correctly
- Running optimization in mock mode for development

## Installation

> **This is the Python SDK skill.** Building in **JavaScript/TypeScript** instead? Use the
> **`traigent-js`** skill — it covers the native JS/TS optimizer (the `@traigent/sdk` package)
> with a different install and API. The rest of this page assumes Python.

### Basic Install

```bash
# Recommended — includes integrations, analytics, and common extras
pip install "traigent[recommended]"

# Minimal, no extras
pip install traigent
```

### Use a virtual environment (do this first)

Install into a project virtualenv — it's standard Python practice and it's the friction-free
path here. A **fresh** venv is enough; you do **not** need `--system-site-packages`.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install "traigent[recommended]"
```

`pip install traigent` resolves from PyPI and pulls `litellm` (a **core dependency**) along with
it, so the keyless mock path — which intercepts `litellm.completion(...)` — works immediately,
with no extra install. Only the LangChain / OpenAI / Anthropic *adapter* clients live in the
`integrations` extra (below).

> **Why a venv instead of system Python?** On modern Debian/Ubuntu/Fedora the system interpreter
> is marked *externally managed* (PEP 668), so a bare `pip install` into it is refused with
> `error: externally-managed-environment`. The venv above avoids that entirely.

### With Optional Extras

```bash
# Framework integrations (LangChain, OpenAI, Anthropic, MLflow, W&B)
pip install 'traigent[integrations]'

# Analytics (numpy, pandas, matplotlib)
pip install 'traigent[analytics]'

# All optional features
pip install 'traigent[all]'

# Enterprise bundle (all production features)
pip install 'traigent[enterprise]'
```

See `references/installation-extras.md` for the full table of extras and their contents.

### Requirements

- Python >= 3.11

## Get Your Traigent API Key

Backend-connected features (the default cloud smart optimizer, dataset synthesis, analytics dashboards, the CI gate, and portal result history) all require `TRAIGENT_API_KEY`. There are two ways to obtain it:

### Portal key (experiments-scoped)

1. Sign up at the Traigent portal and create a project.
2. In your project settings, go to **API Keys** and click **Create key**.
3. This issues a `user`-type key scoped to `experiments:read experiments:write` — sufficient for SDK optimizations and analytics.

```bash
export TRAIGENT_API_KEY="sk_..."
```

### CLI device-authorization key (project-scoped)

The CLI device-flow issues a project-scoped `sk_`-prefixed key with broader permissions (quota, dataset management, full project access). Use this when you need project-level operations beyond experiments.

Run `traigent auth login` in your terminal — it opens a browser for OAuth device authorization. The key is written to `~/.traigent/credentials`. Then export it:

```bash
export TRAIGENT_API_KEY="sk_..."
```

**Which key to use?** The portal experiments-scoped key is sufficient for most optimization workflows. Use the device-flow key for quota management, cross-project access, or when the CLI reports permission errors.

For the standard path, set `TRAIGENT_API_KEY` once, omit `algorithm` and `offline`, and let Traigent use the default cloud smart optimizer with portal result sync. Use `algorithm="grid"` or `"random"` only when you explicitly want local search; use `offline=True` only when zero egress is required.

## Environment Setup

### Development Mode (Recommended for Getting Started)

Mock mode is the keyless dev path for provider calls — LLM calls are intercepted and return canned responses. Activate it in code:

```python
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
```

<!-- PROTECTED -->
- `enable_mock_mode_for_quickstart()` is the recommended activation path. It is **hard-blocked when `ENVIRONMENT=production`** and emits a once-per-process WARNING so a test that accidentally runs in a deployed system is loud and visible.
<!-- /PROTECTED -->
- **Mock scope:** only LiteLLM (`litellm.completion`) and LangChain (`ChatOpenAI`, `ChatAnthropic`, etc.) calls are intercepted. Raw `openai.OpenAI()` / `anthropic.Anthropic()` clients are **not** intercepted — a function using a raw client will make real, billable calls in mock mode. Use LiteLLM in examples that must run keyless.
- **No separate install needed for mock:** `litellm` ships with the SDK *core* (`pip install traigent` pulls it), so `litellm.completion(...)` is interceptable the moment Traigent is installed — you do **not** need to `pip install litellm` yourself. (LangChain adapters do require `pip install 'traigent[integrations]'`.)

### Legacy Env-Var Path

<!-- PROTECTED -->
The previous quickstart docs taught `export TRAIGENT_MOCK_LLM=true`. That env var still works in non-production environments for backward compatibility with existing fixtures, but it is hard-blocked when `ENVIRONMENT=production` (an `OSError` is raised at SDK import). Prefer the in-code API for new code.
<!-- /PROTECTED -->

### Using a .env File

Traigent supports `.env` files via `python-dotenv` (included in the `integrations` extra). Create a `.env` file in your project root:

```
TRAIGENT_API_KEY=sk_...
OPENAI_API_KEY=sk-...
TRAIGENT_DEBUG=1
```

#### Recommended: have the user paste keys into `.env`, never into the chat

When a user says *"I have my key"*, do **not** ask them to type the secret into the
conversation — it would be captured in the agent transcript, logs, and context. Open the
`.env` file for them to paste into directly. This is both **more secure** (the raw key
never touches the chat) and **better UX** (they see exactly where it goes). Procedure:

1. **Create the file** from the project template if one exists (`cp .env.example .env`),
   otherwise create a minimal `.env` with key *names* pre-filled and values blank, so the
   user only pastes after each `=`:
   ```
   TRAIGENT_API_KEY=
   # provider key — fill the one(s) this project uses:
   OPENAI_API_KEY=
   # ANTHROPIC_API_KEY=
   # Bedrock: AWS_ACCESS_KEY_ID= / AWS_SECRET_ACCESS_KEY= / AWS_REGION=
   ```
2. **Always show the user the absolute path** (e.g. `/home/me/proj/.env`). This is the
   guaranteed fallback — they can open it in their own editor no matter what happens next.
3. **Best-effort: pop the file open in a _standalone_ editor window, launched _detached_.**
   Pick the launcher by OS; never wrap it in `timeout`:
   - **Linux:** `setsid -f gnome-text-editor "$ENV"` — or the first of
     `kate` / `gedit` / `xed` / `mousepad` that exists; last resort `xdg-open "$ENV"`.
   - **macOS:** `open -t "$ENV"` (opens the default text editor in its own window).
   - **Windows:** `start "" notepad "%ENV%"` (Notepad is always present), or
     `Start-Process notepad "$env:ENV"` in PowerShell.

   **Pitfalls that look like success but aren't** (verified the hard way):
   - **Don't** open via the user's IDE (`code <file>` / `cursor <file>`): it can spawn a
     nested instance that *crashes*, and it hijacks whichever IDE window is focused — so
     `.env` can pop up inside an unrelated project.
   - **Don't** trust the launcher's exit code as "opened" — a crashed window can still exit 0.
     Verify the editor process is actually alive (e.g. `pgrep`) **and ask the user to confirm
     the window appeared.**
4. **Pick the provider key by detecting the vendor from the project** (its
   `openai` / `anthropic` / `litellm` / Bedrock imports or config). If the vendor is
   ambiguous, undetectable, or the project uses **multiple** providers (e.g. OpenAI *and*
   Bedrock), **ask the user which provider(s)** and label the matching key(s) in `.env`.
5. **Wait** for the user to paste and save. Confirm `.env` is in `.gitignore`.
6. **Fallback:** if no standalone editor opens (or the user says no window appeared), have
   them open the printed path manually; only as a last resort use a terminal `export VAR=...`
   (less private than the file).

> Never echo, log, or read back the key value. `.env` must be git-ignored — never commit real keys.

### Production Mode

For production, set your provider API keys and don't call `enable_mock_mode_for_quickstart()`:

```bash
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...
```

> **Before your first real run, verify your model IDs are live.** Provider catalogs change — a
> delisted or renamed ID causes a 404 or a degraded/unpriced trial. Preflight with
> `traigent models --provider <p> --check <model_id>` (see the CLI Quick Reference below), or
> query the provider's live catalog directly (e.g. `curl -s https://openrouter.ai/api/v1/models`
> for OpenRouter). The `traigent-integrations` skill covers multi-provider model verification.

See `references/environment-variables.md` for all available environment variables.

## Your First Optimization

> **Always dry-run first.** Before a real (paid) run, run in mock mode, review the cost estimate, and get explicit approval. See the `traigent` lifecycle skill for the mandatory dry-run-first / cost-approval workflow.

Here is a complete working example. This function classifies customer queries using an LLM, and Traigent will find the best model and temperature combination.

**Note on mock scope:** `enable_mock_mode_for_quickstart()` intercepts LiteLLM and LangChain calls. Raw `openai.OpenAI()` / `anthropic.Anthropic()` client calls are **not** intercepted — use `litellm.completion()` for a fully keyless dry-run (see `references/installation-extras.md` for `traigent[integrations]`).

**Why the example includes a `mock_demo_accuracy` scorer:** in mock mode every LLM call returns the *same* canned string, so a **real** accuracy metric scores every trial 0.0 — a discouraging all-zeros table that looks broken. The demo scorer below ignores the (canned) output and ranks trials by their config, so the keyless dry-run produces a meaningful table — the same approach the bundled `traigent quickstart` command uses. It is **mock-only: delete it for a real run**, where Traigent scores actual model output against your dataset labels. (Prefer not to keep a placeholder scorer in your own code? Just run `traigent quickstart` for the same ranked demo without writing one.)

```python
import asyncio
import litellm  # pip install traigent[integrations]
import traigent
from traigent import Choices
from traigent.testing import enable_mock_mode_for_quickstart

# Step 1: dry-run in mock mode — no API keys required, no cost
enable_mock_mode_for_quickstart()


def mock_demo_accuracy(output, expected, config=None, **_):
    """Mock-only demo scorer — DELETE this for a real (paid) run.

    In mock mode every ``litellm.completion`` call returns the same canned
    string, so a real accuracy metric would score every trial 0.0 (a
    misleading all-zeros table). This placeholder ignores ``output`` and ranks
    trials by their config so the keyless dry-run produces a meaningful table —
    the same trick the bundled ``traigent quickstart`` demo uses. On a real run,
    remove it and let Traigent score actual model output against your labels.
    """
    cfg = config or traigent.get_config() or {}
    base = 0.85 if cfg.get("model") == "gpt-4o" else 0.65
    return max(0.0, base - 0.05 * float(cfg.get("temperature", 0.5)))


@traigent.optimize(
    eval_dataset="eval_queries.jsonl",
    objectives=["accuracy"],
    model=Choices(["gpt-4o-mini", "gpt-4o"]),
    temperature=Choices([0.0, 0.5, 1.0]),
    metric_functions={"accuracy": mock_demo_accuracy},  # mock-only; delete for a real run
)
def classify_query(query: str) -> str:
    config = traigent.get_config()
    # Use litellm so mock mode intercepts the call (raw openai client is NOT intercepted)
    response = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
        messages=[
            {"role": "system", "content": "Classify the query as: billing, technical, or general."},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content


async def main():
    # Step 1: dry-run (mock) — confirm the setup works and review estimated cost
    results = await classify_query.optimize(max_trials=6)  # default algorithm="auto"

    # Inspect results
    print(f"Best config: {results.best_config}")
    print(f"Best score:  {results.best_score}")
    print(f"Trials run:  {len(results.trials)}")

    # Apply the best configuration for production use
    classify_query.apply_best_config(results)

    # Now calling the function uses the best config
    answer = classify_query("I can't log in to my account")
    print(f"Classification: {answer}")


asyncio.run(main())
```

### Synchronous Alternative

If you prefer synchronous execution:

```python
results = classify_query.optimize_sync(max_trials=6)  # default algorithm="auto"
```

### Key Concepts

1. **`@traigent.optimize(...)`** -- Decorator that wraps your function for optimization. Define what parameters to tune in the decorator arguments.
2. **`traigent.get_config()`** -- Call inside your function to retrieve the current trial's configuration. Works during optimization trials and after `apply_best_config()`.
3. **`func.optimize(max_trials=N)`** -- Run the optimization loop asynchronously. Returns an `OptimizationResult`.
4. **`func.apply_best_config(results)`** -- Lock in the best configuration found so that subsequent calls use it.

> **You've run your first optimization — now make it robust.** The decorator above is intentionally *minimal* (just `model` + `temperature`). For a real optimization, graduate to the more robust **`traigent-decorator-setup`** skill — custom evaluators / `metric_functions`, injection & execution control (`algorithm`/`offline`), and weighted objectives — then launch with **`traigent-run-optimization`**, which adds what a *real* run needs beyond the basic `.optimize()` call: **cost limits** (cap a paid sweep before it overruns), **algorithm choice** (`bayesian`/`optuna` for large search spaces), **parallel trials**, and **quota-aware run sizing**. That `decorator-setup` → `run-optimization` pair is the recommended path from "first run" to a production optimization.

## Dataset Format

Traigent uses JSONL (JSON Lines) files for evaluation datasets. Each line must have an `input` field and an `output` field.

### Example: `eval_queries.jsonl`

```jsonl
{"input": "I was charged twice for my subscription", "output": "billing"}
{"input": "The API returns a 500 error on POST requests", "output": "technical"}
{"input": "What are your business hours?", "output": "general"}
```

- **`input`** -- The value passed to your function during evaluation.
- **`output`** -- The expected/ground-truth result used for scoring.

You can include additional fields for metadata, but `input` and `output` are required.

### Tips for Good Datasets

- Include at least 10-20 examples for meaningful optimization.
- Cover edge cases and diverse inputs.
- Ensure ground-truth `output` values are consistent and well-defined.
- For evaluation dataset creation beyond this minimal JSONL, use `traigent-curate-dataset`.

## Verify Installation

### Check SDK info

```bash
traigent info
```

This prints the installed version, Python version, available integrations, and optimization defaults.

### Verify from Python

```python
import traigent
print(traigent.get_version_info())
```

### Validate an evaluation dataset

```bash
traigent validate eval_queries.jsonl
```

## CLI Quick Reference

**Start here (keyless, no API key required):**

```bash
traigent quickstart      # bundled working demo — mock mode, zero config
traigent onboard         # guided first-run setup wizard
```

| Command                    | Description                                                         |
| -------------------------- | ------------------------------------------------------------------- |
| `traigent quickstart`      | Run the bundled mock-mode demo (keyless, zero-setup, always works)  |
| `traigent onboard`         | Guided setup for Traigent in this project (API key, project, env)   |
| `traigent models`          | List/validate model IDs before a run, e.g. `traigent models --provider anthropic --check claude-3-haiku-20240307` (model preflight; catalogs change) |
| `traigent recommend`       | Evidence-backed TVAR recommendations for your agent/task type       |
| `traigent recommend-eval`  | Metric and evaluator recommendations for your task type             |
| `traigent generate-config` | Scaffold a full `@traigent.optimize()` config for your function     |
| `traigent detect-tvars`    | Detect tuned-variable candidates in existing Python files           |
| `traigent info`            | Show SDK version, environment, and integrations                     |
| `traigent algorithms`      | List available optimization algorithms                              |
| `traigent validate`        | Validate dataset files and configuration                            |

## Next Steps

- **Configure your decorator for a real optimization** -- The example above is the *minimal* decorator. To make it optimization-ready -- custom evaluators / `metric_functions`, injection mode, execution (`algorithm`/`offline`), and weighted objectives -- use the `traigent-decorator-setup` skill, then launch with `traigent-run-optimization`. This `decorator-setup` → `run-optimization` pair is the standard two-step cycle for going from "first run" to a real optimization.
- **Dry-run before a real run** -- See the `traigent` lifecycle skill for the mandatory dry-run-first / cost-approval workflow before any paid execution.
- **Mind your plan quota** -- Cloud optimization is metered by `optimization_samples` (~`max_trials × dataset_size` per run) and `optimization_trials`, separate from dollar cost. Check usage and size large runs to fit; see the `traigent-run-optimization` skill ("Quota & Run Sizing").
- **Define parameter search spaces** -- See the `traigent-configuration-space` skill for `Range`, `IntRange`, `Choices`, `LogRange`, factory presets, and constraints.
- **Choose an optimization algorithm** -- Run `traigent algorithms` to see available options. `"grid"` and `"random"` run locally; `"bayesian"` and `"optuna"` require a Traigent cloud connection.
- **Add multiple objectives** -- Use `objectives=["accuracy", "cost", "latency"]` for multi-objective optimization.
- **Use framework integrations** -- Install `traigent[integrations]` for LangChain, OpenAI, and Anthropic adapters.
- **Verify model IDs before a real run** -- Catalogs change; run `traigent models --provider <p> --check <id>` (or query the provider's live catalog) so a delisted/renamed ID doesn't cause a 404 or a degraded, unpriced trial. See `traigent-integrations`.

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
