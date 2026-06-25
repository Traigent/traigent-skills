---
name: traigent
description: "Guide users through Traigent optimization: setup, dry-run validation, and real execution. Use when a user asks to optimize a function with @traigent.optimize, run an optimization, or set up Traigent. ALWAYS start with dry-run (mock mode) to validate the full pipeline, then switch to real execution only when the user explicitly requests it."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.1.1"
---

# Traigent: Dry-Run First, Real When Ready

<!-- PROTECTED -->
## Your Role

When a user asks you to optimize a function with Traigent, **always start with a dry run**. Real optimization costs real tokens and money. Never run real optimization until the user explicitly asks.
Present a cost estimate and get the user's explicit approval before any paid run.

## The Lifecycle at a Glance

| Stage | Skill |
|---|---|
| Dataset | `traigent-curate-dataset` |
| Metric | `traigent-choose-metric` |
| Evaluator | `traigent-build-evaluator` plus `traigent-evaluator-audit` |
| Optimize | this skill plus `traigent-run-optimization` |
| Iterate | `traigent-iterate` |
| Gate | `traigent-ci-safety-gate` |

After completion, use `traigent-iterate` to choose the next single hypothesis and `traigent-ci-safety-gate` before promoting a winning config.

Planned: a playbook artifact may eventually package this lifecycle; today, follow the skill sequence above.

**Workflow:**

1. Set up the decorated function
2. Validate dataset, config space, and providers
3. Dry-run in mock mode — verify the full pipeline end-to-end at zero cost
4. Report what the dry run found, estimate real costs
5. **Wait** for the user to say "run it for real"
<!-- /PROTECTED -->

## Step 1: Set Up the Decorator

The user's function needs four things:

```python
import traigent
import litellm  # pip install traigent[integrations] — the canonical runnable LLM call
from traigent import Choices, Range

@traigent.optimize(
    eval_dataset="eval_data.jsonl",                    # 1. Dataset
    objectives=["accuracy"],                           # 2. What to optimize
    model=Choices(["gpt-4o-mini", "gpt-4o"]),          # 3. Config space (inline)
    temperature=Range(0.0, 1.0),
)
def my_function(query: str) -> str:                    # 4. The function
    config = traigent.get_config()
    resp = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
        messages=[{"role": "user", "content": query}],
    )
    return resp.choices[0].message.content
```

> **One runnable body, reused everywhere.** The `litellm.completion(...)` → `resp.choices[0].message.content` body above is the canonical, copy-paste-runnable function used across these skills (and in `traigent-quickstart`). Reuse it verbatim wherever an example shows `my_function`/agent body — it runs keyless under mock mode (LiteLLM is intercepted) and unchanged for a real run. **Optimize accuracy *and* cost?** `cost` and `latency` are built-in objectives auto-derived from token accounting, so use `objectives=["accuracy", "cost"]` — no extra evaluator needed.

### Config Space: Inline vs Dict

Parameters can be defined inline on the decorator or in `configuration_space=`:

```python
# Inline (cleaner for simple spaces)
@traigent.optimize(
    model=Choices(["gpt-4o-mini", "gpt-4o"]),
    temperature=Range(0.0, 1.0),
)

# Dict (better for dynamic or large spaces)
@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3, 0.7, 1.0],
        "max_tokens": [256, 512, 1024],
    },
)
```

### Setup Mistakes to Catch

| Mistake | SDK catches? | Fix |
|---|---|---|
| Config values as bare strings (`model="gpt-4"`) | Yes — `TypeError` | Must be list or Range/Choices (`model=Choices(["gpt-4"])`) |
| `get_config()` called outside the function | Yes — `OptimizationStateError` | Must be inside the decorated function body |
| Dataset file doesn't exist | Yes — `ValidationError` | Create it or fix the path |
| **Empty objectives list** | **No — silently defaults** | Verify `objectives` has at least one entry before running |
| **Function doesn't return a value** | **No — `None` scored silently** | Assert your function returns the prediction; `None` produces meaningless scores |

## Step 2: Validate Before Running

Use the SDK's built-in validation tools before any optimization.

### Validate the Dataset

```bash
traigent validate eval_data.jsonl
# With options: traigent validate eval_data.jsonl --objectives accuracy -v
```

Each line must be valid JSON with an `input` field. Include `output` when optimizing accuracy-like metrics:

```jsonl
{"input": "I was charged twice", "output": "billing"}
{"input": "API returns 500 error", "output": "technical"}
{"input": "What are your hours?", "output": "general"}
```

Minimum 5 examples for any signal. 10-20+ recommended.

### Check System and Algorithms

```bash
traigent info        # SDK version, Python version, enabled features
traigent algorithms  # Available algorithms with descriptions and best-use cases
```

### CLI Dry-Run Check

The `traigent check` command validates decorated functions without running real optimization:

```bash
# Dry-run: show what would be checked without running optimization
traigent check my_script.py --dry-run

# Check specific functions
traigent check my_script.py --functions="my_function" --dry-run
```

This discovers `@traigent.optimize` decorated functions and validates that dataset, objectives, and config space are defined in the decorator. It does not validate dataset file contents — use `traigent validate` for that.

## Step 3: Run Mock Optimization

Enable mock mode in code, then run the full optimization pipeline at zero cost. This tests everything — decorator wiring, config sampling, dataset loading, trial execution, scoring — end to end. Mock mode is hard-blocked when `ENVIRONMENT=production`, so this cannot accidentally swap real LLM calls for canned text in a deployed system.

> **Scope note:** `enable_mock_mode_for_quickstart()` flips a *runtime* flag — the LLM interceptors honor it from the moment it's called. It runs AFTER `import traigent`, so any *import-time* behavior of the SDK's optional dependencies (e.g., LiteLLM's model-cost-map fetch) has already executed. For fully hermetic startup (CI, air-gapped runs), set the equivalent env vars BEFORE Python imports anything: `TRAIGENT_MOCK_LLM=true`, `TRAIGENT_OFFLINE_MODE=true`, `LITELLM_LOCAL_MODEL_COST_MAP=True`. The bundled `traigent quickstart` command does this for you.

```python
import os
os.environ["TRAIGENT_OFFLINE_MODE"] = "true"   # Skip Traigent backend calls

import traigent
import litellm  # pip install traigent[integrations]
from traigent import Choices, Range
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()              # Mock LLM responses (dev-only)

@traigent.optimize(
    eval_dataset="eval_data.jsonl",
    objectives=["accuracy"],
    model=Choices(["gpt-4o-mini", "gpt-4o"]),
    temperature=Range(0.0, 1.0),
)
def my_function(query: str) -> str:
    config = traigent.get_config()
    resp = litellm.completion(                  # canonical runnable body (intercepted in mock)
        model=config["model"],
        temperature=config["temperature"],
        messages=[{"role": "user", "content": query}],
    )
    return resp.choices[0].message.content

# Mock optimization — zero cost, validates the full pipeline
results = my_function.optimize_sync(max_trials=4, algorithm="random")

print(f"Trials ran:    {len(results.trials)}")
print(f"Failed trials: {len(results.failed_trials)}")
print(f"Stop reason:   {results.stop_reason}")
print(f"Best config:   {results.best_config}")
print(f"Best score:    {results.best_score}")
```

### Interpret Mock Results

| Check | Pass | Fail |
|---|---|---|
| Trials ran | `len(results.trials) > 0` | No trials = config space or dataset error |
| No failures | `len(results.failed_trials) == 0` | Failures = function or evaluator bug |
| Stop reason | `"max_trials_reached"` or `"optimizer"` | `"error"` = something broke |
| Config keys | Expected keys in `best_config` | Missing keys = config space mismatch |

**Score interpretation depends on your evaluator type:**

- **Config-aware scorer** (reads `traigent.get_config()` or a `config=` kwarg and returns a
  value that varies by trial config): scores differ across trials and are meaningful for
  ranking even in mock mode. This is the pattern used in the `traigent-quickstart` example.
- **Output-based / deterministic scorer** (exact-match, JSON-schema, execution accuracy):
  the mock LLM always returns the **same constant string** (`"This is a mock response for
  testing."` — `traigent/integrations/utils/mock_adapter.py:69`). Every call to the
  decorated function returns that constant, so **all scores will be uniformly 0.0** for
  these scorers. This does **not** mean your agent is broken — it means mock-plumbing is
  confirmed working. Uniform 0.0 under mock is expected for output-based scorers.

> **WARNING — uniform 0.0 under mock is plumbing-OK, not a failure:**
> If your scorer is output-based (exact-match, SQL execution accuracy, JSON-schema, etc.)
> and all mock scores are 0.0, that is the correct expected result: the mock returns a
> constant string that no deterministic scorer can score positively. Focus on whether trials
> ran without errors (`failed_trials == 0`), not on the 0.0 score values.
>
> **Non-degenerate dry-run recipe:** To get a varied score spread without real LLM calls,
> use a config-aware scorer that reads the trial config rather than the constant mock output:
>
> ```python
> def mock_demo_accuracy(output, expected, config=None, **_):
>     """Config-aware scorer for mock dry-runs — scores by config, not output."""
>     cfg = config or traigent.get_config() or {}
>     base = 0.85 if cfg.get("model") == "gpt-4o" else 0.65
>     return max(0.0, base - 0.05 * float(cfg.get("temperature", 0.5)))
> ```
>
> Delete this scorer for your real (paid) run — on a real run, let your output-based
> scorer evaluate actual LLM output. This mock-only scorer is purely for confirming the
> pipeline works end to end before spending API budget.

### If Mock Fails

Enable debug logging:

```bash
export TRAIGENT_DEBUG=1
```

Common failures:
- `ConfigurationError` — Fix decorator arguments (see setup mistakes table)
- `EvaluationError` — Fix scoring function or dataset format
- `OptimizationStateError` — `get_config()` called outside optimization context
- `ModuleNotFoundError` — `pip install traigent[integrations]`
- All trials failed — Test the function standalone with a hardcoded config first

<!-- PROTECTED -->
**Do not proceed to real mode until mock passes cleanly.**
<!-- /PROTECTED -->

## Step 3.5: Evaluator Sanity Gate

Before the first paid run, verify the metric actually separates a correct output from a wrong one. This costs nothing — no LLM calls — but catches the single most expensive silent failure mode: an evaluation metric that swallows exceptions or silently returns 0.0 for every config (making the agent look broken when the metric is broken).

```python
# `my_metric` is the scoring_function / metric you pass to @traigent.optimize.
# Use literal good/bad examples for YOUR task — no LLM call needed (that's the point).
expected_output = "the expected answer for one example"   # your gold label
known_good      = "a known-correct output for that example"  # e.g. the gold answer itself
known_bad       = "obviously wrong or empty output"

assert my_metric(known_good, expected_output) >= 0.9, (
    "metric does not reward a correct output — fix before running real optimization"
)
assert my_metric(known_bad, expected_output) <= 0.1, (
    "metric does not penalize a wrong output — fix before running real optimization"
)
```

For a `custom_evaluator` / `BaseEvaluator`, call `.evaluate([good_example])` and `.evaluate([bad_example])` directly and assert the returned `metrics` separate. Use **one known-good + one known-bad example only** — this is a smoke gate, not a full audit.

> **If both assertions pass:** the metric wires correctly — proceed to Step 4.
>
> **If either fails:** fix the metric before spending tokens. Common causes: wrong field name in the result, inverted logic (`>` vs `<`), exception swallowed to `0.0`. See [traigent-build-evaluator](../traigent-build-evaluator/SKILL.md) for diagnostic steps. For LLM-judge metrics, see [traigent-evaluator-audit](../traigent-evaluator-audit/SKILL.md) for the full reliability protocol.

## Step 4: Report and Estimate Costs

After a successful mock run, tell the user:

1. **Pipeline validated** — trials, config space, dataset all working
2. **Config space size** — how many unique configurations
3. **Estimated LLM calls** — `max_trials x dataset_size` (upper bound)
4. **Cost limit** — default $2.00 USD per run (`TRAIGENT_RUN_COST_LIMIT`)
5. **Ask for go/no-go**

Example:

> Mock run passed: 4/4 trials, 0 failures, pipeline is valid.
>
> Config space: 2 models x continuous temperature. With `max_trials=10` and 15 dataset examples, that's up to 150 LLM calls.
>
> Default cost limit is $2.00 USD. Want me to run it for real? This will use your API keys and cost real tokens.

## Step 5: Run Real Optimization (Only When Asked)

<!-- PROTECTED -->
When the user explicitly says to proceed:
<!-- /PROTECTED -->

### 1. Verify API Keys

Models in the config space need corresponding provider keys. Traigent auto-validates keys before starting and raises `ProviderValidationError` with details if validation fails.

```bash
export OPENAI_API_KEY="sk-..."         # For gpt-* models
export ANTHROPIC_API_KEY="sk-ant-..."  # For claude-* models
export GEMINI_API_KEY="..."            # For gemini-* models
```

### 2. Skip the Mock-Mode Activation and Set Cost Controls

```python
import os

# Just don't call enable_mock_mode_for_quickstart() this run.
# Mock mode is process-local — start a fresh interpreter for the
# real run if the previous one had it on.
os.environ.pop("TRAIGENT_OFFLINE_MODE", None)

# Cost limit — default $2.00 USD per run
os.environ["TRAIGENT_RUN_COST_LIMIT"] = "2.00"
```

### 3. Run Real Optimization

> **Smart algorithms are cloud-only.** `bayesian` (and the rest of the Optuna/Bayesian family,
> incl. `tpe`) run on the Traigent backend and require `TRAIGENT_API_KEY` (`traigent auth`) — the
> provider keys exported above are **not** enough. Without it the run raises `OptimizationError`.
> For a fully local real run, use `algorithm="grid"` or `algorithm="random"`.

```python
from traigent.utils.exceptions import CostLimitExceeded, OptimizationError

try:
    # `bayesian` is cloud-only (needs TRAIGENT_API_KEY); use "grid"/"random" to stay local.
    results = my_function.optimize_sync(max_trials=10, algorithm="bayesian")
except CostLimitExceeded as e:
    print(f"Budget hit: ${e.accumulated:.2f} / ${e.limit:.2f}")
    print("Increase TRAIGENT_RUN_COST_LIMIT to allow more spending.")
    raise
except OptimizationError as e:
    # e.g. a cloud-only algorithm with no TRAIGENT_API_KEY set.
    print(f"Optimization could not run: {e}")
    print("Set TRAIGENT_API_KEY for smart algorithms, or use algorithm='grid'/'random'.")
    raise

print(f"Best config:  {results.best_config}")
print(f"Best score:   {results.best_score}")
print(f"Total cost:   ${results.total_cost:.2f}" if results.total_cost else "")
print(f"Duration:     {results.duration:.1f}s")
print(f"Stop reason:  {results.stop_reason}")
```

### 4. Export a candidate, gate, then apply

Do not promote the winner straight into production. Export it as a
candidate, check it on a held-out slice (see `traigent-ci-safety-gate`
for the promotion gate and CI checks), and apply only after the gate
and the user's explicit approval.

```python
# Export the winning config as a CANDIDATE artifact for review/gating
my_function.export_config("candidate_config.json")

# After the holdout/promotion gate passes and the user approves:
my_function.apply_best_config(results)
answer = my_function("What is Python?")
```

## Quick Reference

| | Mock (Dry Run) | Real |
|---|---|---|
| Activation | `traigent.testing.enable_mock_mode_for_quickstart()` | (don't call it) |
| `TRAIGENT_OFFLINE_MODE` | `true` | unset |
| API keys needed | No | Yes |
| LLM calls | Mocked | Real |
| Cost | $0 | Real tokens |
| Scores meaningful | Custom scorer recommended (built-in mock returns generic text) | Yes |
| Production-safe | Hard-blocked when `ENVIRONMENT=production` | — |
| Use when | Always first | After mock passes |

## See Also

- `traigent-quickstart` — Installation and first-time setup
- `traigent-configuration-space` — Range, Choices, IntRange, LogRange, constraints
- `traigent-decorator-setup` — EvaluationOptions, InjectionOptions, ExecutionOptions
- `traigent-run-optimization` — Algorithms, cost limits, parallel execution
- `traigent-analyze-results` — Interpret results, compare trials, apply best config
- `traigent-debugging` — Error diagnosis and troubleshooting

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
