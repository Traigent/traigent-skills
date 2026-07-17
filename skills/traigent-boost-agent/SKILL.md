---
name: traigent-boost-agent
description: "End-to-end lifecycle playbook — from a single decorated function to a full 12-step codebase onboarding — for adding Traigent to an existing client agent codebase and measurably boosting accuracy, cost, latency, or reliability. Use when asked to add Traigent to this agent, onboard this agent to Traigent end-to-end, run a full agent-build lifecycle, wire an evaluator and optimize, boost accuracy/cost of an existing agent codebase, select TVARs with recommend_configuration_space(), choose composite knobs by agent shape, instrument @traigent.optimize minimally, validate in mock mode, run real optimization with budgets, inspect results, iterate, gate a promoted config, optimize a function with @traigent.optimize, run an optimization, or set up Traigent optimization. ALWAYS start with dry-run (mock mode) to validate the full pipeline, then switch to real execution only when the user explicitly requests it."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "2.1.7"
---

# Traigent Boost Agent

<!-- PROTECTED -->
## Your Role

When a user asks you to optimize a function or agent with Traigent, **always start with a dry run**. Real optimization costs real tokens and money. Never run real optimization until the user explicitly asks.
Present a cost estimate and get the user's explicit approval before any paid run.

**Workflow:**

1. Set up the decorated function (for a single function, see the Fast Path below; for a whole codebase, Steps 1-7 of the 12-Step Lifecycle Playbook)
2. Validate dataset, config space, and providers
3. Dry-run in mock mode — verify the full pipeline end-to-end at zero cost
4. Report what the dry run found, estimate real costs
5. **Wait** for the user to say "run it for real"
<!-- /PROTECTED -->

## When to Use

Requires `traigent>=0.13.0` (the knobs API is present on all current SDK releases).

Use this skill when the user asks you to:

- "add Traigent to this agent"
- "optimize this agent"
- "boost accuracy/cost of an existing agent codebase"
- "onboard this agent to Traigent end-to-end"
- "full agent-build lifecycle"
- "wire an evaluator and optimize"
- instrument an existing LLM, RAG, tool-using, coding, or multi-stage agent with Traigent
- choose tuned variables and composite knobs for a real client codebase

For detailed grep patterns and evidence-mining heuristics, read `references/codebase-analysis.md`. For a minimal before/after implementation recipe, read `references/instrument-recipe.md`. For insight and iteration code, read `references/insights-and-iteration.md`.

## Optimization Economics — Read This Before Sizing a Run

**Do not default to recommending zero spend.** The canonical Traigent posture on spending,
the five characterization questions with their exact options, the tailoring rules, the
explanation duty, and the local survey draft contract all live in one place:
**`docs/shared/economics-characterization.v0.md`**. Read it before you propose, size, or
decline a run — it is the source of truth and is deliberately not restated here.

**This skill's part:** characterize the value the client agent creates, then propose a
bounded first experiment sized to it.

**Mandatory whenever you relay any of it:** show the options, recommend exactly one, and
explain **why in the user's own numbers** — their agent, their volumes, their error costs. The
explanation is a product requirement, not decoration.

Safety is unchanged and unweakened: mock/dry-run first, **explicit user approval before any
paid run**, an explicit spend cap, and the recorded stop rule. The economics reference sets
*how much* to invest; it never affects *whether* approval is required — it always is.

## Fast Path: Optimize a Single Function

For a single decorated function (rather than a whole codebase), run this condensed dry-run-first sequence; the 12-Step Lifecycle Playbook below is the full-codebase version.

### Step 1: Set Up the Decorator

The user's function needs four things: dataset, objectives, config space, and the function itself.

```python
import traigent
import litellm  # pip install "traigent[integrations]>=0.19" — the canonical runnable LLM call
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

> **One runnable body, reused everywhere.** The `litellm.completion(...)` → `resp.choices[0].message.content` body above is the canonical, copy-paste-runnable function used across these skills. Reuse it verbatim wherever an example shows `my_function`/agent body — it runs keyless under mock mode (LiteLLM is intercepted) and unchanged for a real run. **Optimize accuracy *and* cost?** `cost` and `latency` are built-in objectives auto-derived from token accounting, so use `objectives=["accuracy", "cost"]` — no extra evaluator needed. See `traigent-setup-quickstart` for the full copy-paste example, `traigent-optimize-config-space` for `Range`/`Choices`/`IntRange`/`LogRange`/constraints, and `traigent-setup-decorator` for `EvaluationOptions`/`InjectionOptions`/`ExecutionOptions`.

#### Setup Mistakes to Catch

| Mistake | SDK catches? | Fix |
|---|---|---|
| Config values as bare strings (`model="gpt-4"`) | Yes — `TypeError` | Must be list or Range/Choices (`model=Choices(["gpt-4"])`) |
| `get_config()` called outside the function | Yes — `OptimizationStateError` | Must be inside the decorated function body |
| Dataset file doesn't exist | Yes — `ValidationError` | Create it or fix the path |
| **Empty objectives list** | **No — silently defaults** | Verify `objectives` has at least one entry before running |
| **Function doesn't return a value** | **No — `None` scored silently** | Assert your function returns the prediction; `None` produces meaningless scores |

### Step 2: Validate Before Running

Use the SDK's built-in validation tools before any optimization:

```bash
traigent validate eval_data.jsonl --objectives accuracy -v   # dataset: valid JSON, `input` field (+ `output` for accuracy-like metrics); 5+ examples, 10-20+ recommended
traigent info                                                 # SDK version, Python version, enabled features
traigent algorithms                                           # Available algorithms with descriptions and best-use cases
traigent check my_script.py --dry-run                         # discovers @traigent.optimize functions; validates decorator wiring only, not dataset contents
```

### Step 3: Run Mock Optimization

Enable mock mode in code, then run the full optimization pipeline end to end (decorator wiring, config sampling, dataset loading, trial execution, scoring) with LLM calls intercepted. Mock mode is hard-blocked when `ENVIRONMENT=production`. For mock-mode setup mechanics and scope (what is and isn't intercepted, mock vs offline), see `traigent-setup-quickstart`.

> Mock dry-runs still consume the plan's `optimization_samples` quota, and mock intercepts LiteLLM/LangChain calls only — raw `openai`/`anthropic` clients are NOT intercepted and still bill. See `traigent-debugging` for the quota entry and hermetic-startup env vars (`TRAIGENT_MOCK_LLM`, `TRAIGENT_OFFLINE_MODE`, `LITELLM_LOCAL_MODEL_COST_MAP`).

```python
import os
os.environ["TRAIGENT_OFFLINE_MODE"] = "true"   # Skip Traigent backend calls

import traigent
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()              # Mock LLM responses (dev-only)

# Same @traigent.optimize-decorated my_function as Step 1 —
# its litellm.completion(...) call is intercepted automatically in mock mode.
results = my_function.optimize_sync(max_trials=4, algorithm="random")

print(f"Trials ran:    {len(results.trials)}")
print(f"Failed trials: {len(results.failed_trials)}")
print(f"Stop reason:   {results.stop_reason}")
print(f"Best config:   {results.best_config}")
print(f"Best score:    {results.best_score}")
```

#### Interpret Mock Results

| Check | Pass | Fail |
|---|---|---|
| Trials ran | `len(results.trials) > 0` | No trials = config space or dataset error |
| No failures | `len(results.failed_trials) == 0` | Failures = function or evaluator bug |
| Stop reason | `"max_trials_reached"` or `"optimizer"` | `"error"` = something broke |
| Config keys | Expected keys in `best_config` | Missing keys = config space mismatch |

Score interpretation depends on evaluator type: a config-aware scorer (reads `traigent.get_config()`) produces meaningful varied scores even in mock mode; an output-based/deterministic scorer (exact-match, JSON-schema, execution accuracy) sees the mock LLM's constant response and scores uniformly 0.0.

> **WARNING — uniform 0.0 under mock is plumbing-OK, not a failure:**
> If your scorer is output-based (exact-match, SQL execution accuracy, JSON-schema, etc.)
> and all mock scores are 0.0, that is the correct expected result: the mock returns a
> constant string that no deterministic scorer can score positively. Focus on whether trials
> ran without errors (`failed_trials == 0`), not on the 0.0 score values.
>
> For a varied score spread without real LLM calls, wire a config-aware mock-only demo
> scorer (delete it for the real run) — see `traigent-setup-quickstart` (`mock_demo_accuracy`)
> for the recipe.

If mock fails, set `export TRAIGENT_DEBUG=1` for debug logging, fix decorator args for `ConfigurationError` (see mistakes table above), and see `traigent-debugging` (`references/mock-mode.md`) for the full mock failure diagnosis (evaluation errors, `get_config()` outside optimization context, missing integrations extra, all-trials-failed).

<!-- PROTECTED -->
**Do not proceed to real mode until mock passes cleanly.**
<!-- /PROTECTED -->

### Step 3.5: Evaluator Sanity Gate

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
> **If either fails:** fix the metric before spending tokens. Common causes: wrong field name in the result, inverted logic (`>` vs `<`), exception swallowed to `0.0`. See [traigent-eval-build](../traigent-eval-build/SKILL.md) for diagnostic steps. For LLM-judge metrics, see [traigent-eval-audit](../traigent-eval-audit/SKILL.md) for the full reliability protocol.

### Step 3.6: Tiny Real Cost and KPI Probe

After mock mode and the evaluator sanity gate pass, run one tiny **real** optimization before any full run: 1-2 dataset examples, minimal trials, and the cheapest candidate model (pennies, not dollars). Check both surfaces: `results.total_cost` must be neither `None` nor `0.0` with real calls (both mean cost is not wired), and each trial's `metrics` must contain the declared objectives with non-degenerate values (not all `0.0`/all `1.0`). If either surface fails, wire it before scaling up — see `traigent-optimize-run` → Cost Wiring Probe for the fix ladder (custom model pricing env vars, per-trial cost metrics, strict accounting).

### Step 4: Report and Estimate Costs

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

### Step 5: Run Real Optimization (Only When Asked)

<!-- PROTECTED -->
When the user explicitly says to proceed:
<!-- /PROTECTED -->

Verify API keys first — models in the config space need corresponding provider keys, and Traigent auto-validates them before starting, raising `ProviderValidationError` with details if validation fails:

```bash
export OPENAI_API_KEY="sk-..."         # For gpt-* models
export ANTHROPIC_API_KEY="sk-ant-..."  # For claude-* models
export GEMINI_API_KEY="..."            # For gemini-* models
```

Then skip the mock-mode activation and set cost controls:
```python
import os

# Just don't call enable_mock_mode_for_quickstart() this run.
# Mock mode is process-local — start a fresh interpreter for the
# real run if the previous one had it on.
os.environ.pop("TRAIGENT_OFFLINE_MODE", None)

# Cost limit — default $2.00 USD per run
os.environ["TRAIGENT_RUN_COST_LIMIT"] = "2.00"

# Real runs are blocked by the cost-approval gate until this is set.
# Set it ONLY after the user has seen the cost estimate and explicitly
# approved the spend — never set it preemptively on the user's behalf.
os.environ["TRAIGENT_COST_APPROVED"] = "true"
```

> **Algorithm selector.** For connected real runs, omit `algorithm` or use `algorithm="auto"`.
> `auto` is the default connected path to real cloud Optuna TPE. Use
> `algorithm="grid"` / `"random"` only for explicit local/offline search.
>
> **Named smart selectors execute on connected runs since 0.20.1**
> (see version-matrix: `smart-selector-exec`). On an authenticated connected run, supported names
> (`bayesian`/`tpe`/`optuna`/`optuna_tpe`/`optuna_random`) bind to the typed backend Optuna
> strategy at session creation; unsupported smart names such as `nsga2`/`cmaes` fail fast with
> a capability message (Traigent/Traigent#1752, #1758; on 0.20.0 no named smart selector
> executed end-to-end). They never run locally: with `offline=True` the decorator raises
> `ConfigurationError`, and the local optimizer registry raises `OptimizationError`.

```python
from traigent.utils.exceptions import CostLimitExceeded, OptimizationError

try:
    # Connected real run: omit algorithm or use "auto". Smart selector names
    # like "bayesian" are connected-only (SDK 0.20.1+) and never run locally.
    results = my_function.optimize_sync(max_trials=10, algorithm="auto")
except CostLimitExceeded as e:
    print(f"Budget hit: ${e.accumulated:.2f} / ${e.limit:.2f}")
    print("Increase TRAIGENT_RUN_COST_LIMIT to allow more spending.")
    raise
except OptimizationError as e:
    print(f"Optimization could not run: {e}")
    raise

print(f"Best config:  {results.best_config}")
print(f"Best score:   {results.best_score}")
if results.total_cost:
    print(f"Total cost:   ${results.total_cost:.2f}")
else:
    # None or 0.0 after real calls = cost is NOT wired (see Step 3.6) —
    # say so loudly instead of hiding the row.
    print("Total cost:   NOT TRACKED — wire cost before the next run (Step 3.6)")
print(f"Duration:     {results.duration:.1f}s")
print(f"Stop reason:  {results.stop_reason}")
```

> **Never mock the real run.** Before reporting these numbers, confirm this wasn't a mock/offline
> run in disguise — `total_cost` should be positive and per-trial outputs should vary, not the
> mock's constant response / uniform scores. See `traigent-optimize-run` → "Never mock the real
> run" for the full check and recovery steps.

For algorithm choices, parallel execution, and further cost-limit controls, cross-reference `traigent-optimize-run`; for interpreting `OptimizationResult` beyond this snippet, cross-reference `traigent-analyze-results`. Do not promote the winner straight into production: export it as a candidate, check it on a held-out slice (see `traigent-ci-safety-gate` for the promotion gate and CI checks), and apply only after the gate and the user's explicit approval:

```python
# Export the winning config as a CANDIDATE artifact for review/gating
my_function.export_config("candidate_config.json")

# After the holdout/promotion gate passes and the user approves:
my_function.apply_best_config(results)
answer = my_function("What is Python?")
```

### Quick Reference

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

## The 12-Step Lifecycle Playbook

1. ANALYZE the client codebase before writing code.
   - Find LLM call sites, prompt construction, retrieval steps, tool loops, validators, judges, retries, and postprocessors.
   - Useful greps: raw SDK calls (`chat.completions.create`, `responses.create`, `messages.create`), framework calls (`ChatOpenAI`, `ChatAnthropic`, `Runnable`, `AgentExecutor`, `create_react_agent`, `litellm.completion`), retrieval (`similarity_search`, `as_retriever`, `rerank`), and loop/control terms (`tool_calls`, `function_call`, `critic`, `judge`, `repair`, `retry`).
   - Identify the agent SHAPE: single LLM call, cheap-vs-expensive model path, multi-stage chain, input router, tool loop, generate-then-check, specialists, fallback, or iterative refinement.
   - Pick the smallest function enclosing the scoreable agent behavior. Do not decorate an app route, auth layer, retry wrapper, or generic provider client if the actual input/output to evaluate is higher level.
   - Use `references/codebase-analysis.md` for grep patterns, shape markers, and codebase-specific evidence mining.

2. CURATE the evaluation dataset.
   - Start from existing fixtures, golden sets, accepted traces, support tickets, or redacted logs before synthesizing new examples.
   - Reserve the holdout slice BEFORE the first optimization run and record the partition (tuning slice / optional exemplar bank / holdout slice); if none exists yet, create one before any result counts as promotion-ready.
   - Keep tuning and holdout slices separate, stratify by known input classes, and report sample count, source, label quality, and exclusions.
   - Use JSONL with scoreable `input` and `output` fields when a built-in evaluator can score the task.
   - Mock/offline-check a tiny slice before any backend generation or paid provider work.
   - DELEGATE: `traigent-dataset-curate` owns dataset recipes, growth, example scoring, and quality loops.

3. CHOOSE the metric.
   - Decide what "good" means before writing optimizer code: task success, correctness, cost, latency, safety, reliability, or a measured combination.
   - Prefer built-in objective names when they match the product decision; use custom metric functions only when domain logic is checkable and necessary.
   - Default: at least one objective labeled `accuracy` (built-in objective or your `metric_functions` key). If accuracy doesn't apply to this problem, name the primary quality KPI after the product concept and note why accuracy was skipped.
   - Treat must-not-violate behavior as a safety constraint or promotion gate, not as an ordinary objective to trade away.
   - DELEGATE: `traigent-eval-choose-metric` owns the metric interview and objective vocabulary.

4. WIRE OR BUILD the evaluator.
   - Use the wire-first ladder: `eval_dataset` -> `scoring_function` -> `metric_functions` -> `custom_evaluator` -> `BaseEvaluator`.
   - Start deterministic when the task has ground truth or checkable domain logic; use LLM judges only when deterministic scoring cannot express the quality target.
   - Audit any LLM judge before trusting it to drive optimization.
   - DELEGATE: `traigent-eval-build` owns evaluator code; `traigent-eval-audit` owns judge reliability checks.

5. SELECT TVARS from the public recommendation catalog.
   - Use only the real SDK helpers:

```python
from traigent.config_generator.recommendations import (
    RECOMMENDATION_CAVEAT,
    list_recommendation_agent_types,
    recommend_configuration_space,
)

valid_agent_types = list_recommendation_agent_types()
recommendations = recommend_configuration_space(
    "code_gen",  # or "rag"
    min_impact=None,
    min_confidence=None,
)
configuration_space = recommendations["configuration_space"]
print(recommendations["caveat"] or RECOMMENDATION_CAVEAT)
```

   - Valid public agent types are returned by `list_recommendation_agent_types()`; the current catalog exposes `code_gen` and `rag`.
   <!-- PROTECTED -->
   - Treat `RECOMMENDATION_CAVEAT` as mandatory user-facing context: recommendations are search-space starting points, not universal performance claims.
   <!-- /PROTECTED -->
   - For coding agents, `recommend_configuration_space("code_gen")` includes the `agent_computer_interface` knob pack: `repo_context_strategy`, `file_view_window`, `edit_granularity`, `test_selection_strategy`, and `patch_review_mode`. Its CVAR vocabulary and manual runtime guidance live in each row's `apply_guidance`.
   - For long-context/RAG agents, `recommend_configuration_space("rag")` includes `retrieval_k` plus the `context_budget` knob pack: `context_selection_policy`, `context_order`, `summary_style`, `compression_ratio`, and `citation_policy`. Its CVAR vocabulary and manual runtime guidance also live in `apply_guidance`.
   - For range syntax, constraints, and typed parameters, cross-reference `traigent-optimize-config-space` instead of duplicating it.
   - **Catalog fallback**: if the client's agent shape matches no catalog type
     (e.g. a single-call classifier — neither `code_gen` nor `rag`), drive the
     configuration space from the client's REAL knobs (prompt/style variants,
     temperature, sample count) instead of forcing a catalog type. Still print
     the caveat; note in the report that the space is client-derived.

6. SELECT A COMPOSITE with this SHAPE-to-PATTERN decision table.

| Agent shape | Composite pattern | Use when |
|---|---|---|
| Single LLM call with sampling upside | `self_consistency` or `best_of_n` | Repeated candidates can improve a vote or judge-selected answer. |
| Cheap-vs-expensive model choice | `binary_cascade` | Start cheap and escalate to expert only when the margin is weak. |
| Multi-stage chain | `n_cascade` | Ordered stages escalate through three or more arms. |
| Input classes need different handling | `router` | Dispatch before execution using input adequacy or class signals. |
| Tool loop | `react_tool_loop` | The agent plans one tool step per iteration and stops on confidence. |
| Generate-then-check | `verification_gate` | Draft, verify, and revise based on a verifier pass score. |
| Multiple specialist prompts/models | `moe` | Several experts answer and a vote or judge aggregates them. |
| Primary plus backup | `fallback` | Try a primary path, then backup arms on no-accept or low margin. |
| Iterative draft improvement | `self_refine` / `bounded_refine_loop` | Improve a threaded draft until an acceptance signal passes or a literal iteration cap is hit. |

   - For exact factory signatures, `StageRunner`/`LoopBodyRunner` wiring, `execute_composite`, and telemetry, cross-reference `traigent-optimize-composite-knobs`; do not duplicate its catalog.
   - DELEGATE: `traigent-optimize-composite-knobs` owns composite factory details and runtime wiring.

7. INSTRUMENT minimally and preserve behavior.
   - Wrap the chosen scoreable function with `@traigent.optimize`.
   - Keep the original function signature stable: same name and input parameters. If production callers require a plain output but evaluation returns `(output, metrics)`, add a thin outer adapter rather than changing the call-site inputs.
   - Merge catalog recommendations, local knobs, and composite members:

```python
CONFIGURATION_SPACE = {
    **recommendations["configuration_space"],
    "model": ["gpt-4o-mini", "gpt-4o"],
    "temperature": [0.0, 0.2, 0.7],
    "candidate_count": [1, 2, 3],
    **COMPOSITE.members,
}
```

   - Inside the function, read `cfg = traigent.get_config()`, route tuned values into the real prompt/retriever/tool/model call, execute the composite if selected, and return exactly `(output, metrics)` when you need per-trial numeric measures.
   <!-- PROTECTED -->
   - Keep metrics content-free where required: accuracy, pass rate, cost, latency, token counts, route ids, iteration counts, and composite telemetry are fine. Do not put prompts, answers, retrieved documents, secrets, or PII into metrics.
   <!-- /PROTECTED -->
   - Use `references/instrument-recipe.md` for the smallest before/after code diff.

8. VALIDATE in mock mode FIRST.
   - Cross-reference `traigent-setup-quickstart` and `traigent-debugging` for mock/offline setup.
   - Use `from traigent.testing import enable_mock_mode_for_quickstart` plus `TRAIGENT_OFFLINE_MODE=true` for keyless development.
   - Confirm dataset loading, config sampling, stage wiring, tuple-return unpacking, and zero failed trials before real provider calls.
   - Machine-checkable success contract — assert this instead of eyeballing the table:
     `assert results.trials, "no trials ran"` · `assert not getattr(results, "failed_trials", []), f"failed trials: {results.failed_trials}"` · `assert results.best_config is not None, "no best config selected"`.
   - Mock reality: mock still consumes `optimization_samples` quota; exact/execution-match scorers read uniform 0.0 under mock (expected, not broken); raw `openai`/`anthropic` clients are not intercepted and still bill.
   - DELEGATE: `traigent-setup-quickstart` owns first-run setup; `traigent-debugging` owns mock/offline failure diagnosis.

9. OPTIMIZE for real only with cost limits and explicit approval.
   - Cross-reference `traigent-optimize-run` for `func.optimize()`, `optimize_sync()`, algorithms, `max_trials`, parallelism, and `CostLimitExceeded`.
   - Set an explicit `TRAIGENT_RUN_COST_LIMIT` and verify provider keys before the real run. If a Traigent backend is used, set `TRAIGENT_API_KEY` and `TRAIGENT_BACKEND_URL` as appropriate for the client environment. See [Getting your Traigent API key](../traigent-setup-quickstart/SKILL.md#get-your-traigent-api-key) if you have not yet obtained `TRAIGENT_API_KEY`.
   - Present a cost estimate and get the user's explicit approval before any paid run. The approval signal depends on context: interactive real runs are gated by `TRAIGENT_COST_APPROVED=true` (set only after the user approves the estimate); CI/offline runs (including mock wiring checks under `CI=true`) require `TRAIGENT_RUN_APPROVED=1` instead — see `traigent-ci-safety-gate`.
   - Start with a bounded trial budget, keep the current production baseline in the search space, and save results artifacts for audit.
   - DELEGATE: `traigent-optimize-run` owns algorithms, budgets, and execution controls.

10. INSIGHT: configurations AND examples.
   - Configuration side: start with `get_optimization_insights(results)`, then use `traigent-analyze-variable-importance` for importance-backed knob ranking.
   - Example side: use `ExampleInsightsClient` to compute example scores, read scores, and read dataset-quality metadata. Its reportable scope is non-signal metadata; do not claim hidden difficulty, informativeness, ambiguity, or causal signal values.
   - Core `ExampleInsightsClient` import warns deprecated since 0.13.x (see version-matrix: `exampleinsights-deprecation`): importing it from core `traigent.analytics` emits a `DeprecationWarning` pointing at the `traigent-analytics` plugin — but the plugin does not export this class, so keep the core import and ignore the warning for this class. If the plugin IS installed, the core shim stops exposing the class; use the deep import `from traigent.analytics.example_insights import ExampleInsightsClient` (see the verified import note in `traigent-dataset-curate`).
   - Report baseline vs `results.best_config` delta for the agreed metrics, cost, token use, trial count, failed trials, and `results.stop_reason`.
   - Use `traigent-analyze-results` for `OptimizationResult` inspection and `traigent-analyze-variable-importance` to explain which knobs mattered.
   <!-- PROTECTED -->
   - If results are flat, noisy, failed, or negative, call it a no-boost result. Do not hide it or promote a winner that does not beat the baseline on the evaluation dataset.
   <!-- /PROTECTED -->
   - When wire-proofing against a Traigent backend, expect the run's
     configuration-record count to differ from `len(results.trials)` — the
     backend de-duplicates/aggregates repeated configs. Assert your claims
     (e.g. composite telemetry present) over the RETURNED records, and note
     that aggregate `results.total_cost` can be `None` even when per-trial
     cost measures are `0.0`.
   - Full code lives in `references/insights-and-iteration.md`.
   - DELEGATE: `traigent-analyze-results` owns result-object depth; `traigent-analyze-variable-importance` owns richer TVAR importance reporting.

11. RECOMMEND the most promising next steps.
   - Point at the symptom-to-action table in `references/insights-and-iteration.md` and choose one next hypothesis, not a bundle of unrelated changes.
   - Use example-side findings only as evidence for targeted curation or heldout checks.
   - Planned: a backend next-steps endpoint may eventually package these recommendations; until then, use the manual symptom-to-action table.
   - DELEGATE: `traigent-analyze-guidance` owns post-run next-action selection.

12. COMPLETE: recommend the safety gate and CI checks.
   - In-run `safety_constraints` is planned but not yet implemented (raises `NotImplementedError` at decoration time — see `traigent-ci-safety-gate`); do not teach it as usable today.
   - Use `PromotionGate` for candidate-vs-incumbent decisions on the same holdout — the working gating mechanism today.
   - Recommend SAFETY and EFFICIENCY CI jobs before promotion: holdout regression for safety, plus cost and latency budget checks for efficiency.
   - DELEGATE: `traigent-ci-safety-gate` owns safety constraints, promotion gates, and CI recipes.

<!-- PROTECTED -->
## Claim scope

- End-to-end optimization results are observations from the client's evaluation dataset and run conditions.
- Insights are observations, not causes, unless supported by parameter-importance evidence.
- Gate decisions are statistical decisions on the evaluation dataset.
- Per-variable calibration certificates are the only procedural calibration claims; they do not certify future product behavior.
- Acceptable winner wording: `Calibration-backed winner (client-attested)`.
- Never say `guarantee`, never imply universal lift, and never present catalog recommendations as proof that the client agent will improve.
<!-- /PROTECTED -->

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

### Fetch the live profile (when available)
At session or skill start, if a configured Traigent client is available, seed the profile from the
backend with the skill name:

```python
policy = None
try: policy = await client.get_interaction_policy(skill="<this skill>")
except Exception: pass
```

Treat the returned `profile` as the STARTING seed: its control/expertise/pace axes plus
`question_budget`, `options_max`, and `jargon_level` replace the static defaults below. Explicit user
corrections in-conversation ALWAYS override the seed. If the call is unavailable or
`fallback_policy="static_v1"`, simply use the static defaults below; the SDK already fails soft.

- Always be concise.
- Match terminology to expertise. For `se`: plain engineering words; define each Traigent or
  statistics term once in plain language (no Bayesian / variance-decomposition / Pareto jargon
  unless asked). For `ds`: compact optimization and statistical terms are fine.
- Presenting options: show at most 3, mark exactly one **Recommended**, and give one short
  persona-appropriate trade-off per option.
- Autonomy. For `delegate` or `execute`: pick the recommended reversible action and proceed, asking
  only at hard gates. For `guided`: offer options with a recommendation at the key decisions. For
  `inspect` or `explore`: give brief rationale or evidence before asking, and ask before branch
  choices.
- Hard gates — always confirm regardless of persona: paid or provider model calls, sending data or
  private content off the machine, destructive edits, decisions the Traigent service is meant to
  return, and any missing fact the step truly requires.
- Always end by recommending the next Traigent skill or action to take.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
