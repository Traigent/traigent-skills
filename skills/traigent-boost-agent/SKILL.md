---
name: traigent-boost-agent
description: "End-to-end playbook for adding Traigent to an existing client agent codebase and measurably boosting accuracy, cost, latency, or reliability. Use when asked to add Traigent to this agent, optimize this agent, boost accuracy/cost of an existing agent codebase, select TVARs with recommend_configuration_space(), choose composite knobs by agent shape, instrument @traigent.optimize minimally, validate in mock mode, run real optimization with budgets, or report baseline-vs-winner honestly."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0"
---

# Traigent Boost Agent

## When to Use

Use this skill when the user asks you to:

- "add Traigent to this agent"
- "optimize this agent"
- "boost accuracy/cost of an existing agent codebase"
- instrument an existing LLM, RAG, tool-using, coding, or multi-stage agent with Traigent
- choose tuned variables and composite knobs for a real client codebase

For detailed grep patterns and dataset-building heuristics, read `references/codebase-analysis.md`. For a minimal before/after implementation recipe, read `references/instrument-recipe.md`.

## The playbook

1. ANALYZE the client codebase before writing code.
   - Find LLM call sites, prompt construction, retrieval steps, tool loops, validators, judges, retries, and postprocessors.
   - Useful greps: raw SDK calls (`chat.completions.create`, `responses.create`, `messages.create`), framework calls (`ChatOpenAI`, `ChatAnthropic`, `Runnable`, `AgentExecutor`, `create_react_agent`, `litellm.completion`), retrieval (`similarity_search`, `as_retriever`, `rerank`), and loop/control terms (`tool_calls`, `function_call`, `critic`, `judge`, `repair`, `retry`).
   - Identify the agent SHAPE: single LLM call, cheap-vs-expensive model path, multi-stage chain, input router, tool loop, generate-then-check, specialists, fallback, or iterative refinement.
   - Pick the smallest function enclosing the scoreable agent behavior. Do not decorate an app route, auth layer, retry wrapper, or generic provider client if the actual input/output to evaluate is higher level.

2. SELECT TVARS from the public recommendation catalog.
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
   - For range syntax, constraints, and typed parameters, cross-reference `traigent-configuration-space` instead of duplicating it.
   - **Catalog fallback**: if the client's agent shape matches no catalog type
     (e.g. a single-call classifier — neither `code_gen` nor `rag`), drive the
     configuration space from the client's REAL knobs (prompt/style variants,
     temperature, sample count) instead of forcing a catalog type. Still print
     the caveat; note in the report that the space is client-derived.

3. SELECT A COMPOSITE with this SHAPE-to-PATTERN decision table.

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

   - For exact factory signatures, `StageRunner`/`LoopBodyRunner` wiring, `execute_composite`, and telemetry, cross-reference `traigent-composite-knobs`; do not duplicate its catalog.

4. INSTRUMENT minimally and preserve behavior.
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

5. VALIDATE in mock mode FIRST.
   - Cross-reference `traigent-quickstart` and `traigent-debugging` for mock/offline setup.
   - Use `from traigent.testing import enable_mock_mode_for_quickstart` plus `TRAIGENT_OFFLINE_MODE=true` for keyless development.
   - Confirm dataset loading, config sampling, stage wiring, tuple-return unpacking, and zero failed trials before real provider calls.

6. OPTIMIZE for real only with cost limits.
   - Cross-reference `traigent-run-optimization` for `func.optimize()`, `optimize_sync()`, algorithms, `max_trials`, parallelism, and `CostLimitExceeded`.
   - Set an explicit `TRAIGENT_RUN_COST_LIMIT` and verify provider keys before the real run. If a Traigent backend is used, set `TRAIGENT_API_KEY` and `TRAIGENT_BACKEND_URL` as appropriate for the client environment.
   - Start with a bounded trial budget, keep the current production baseline in the search space, and save results artifacts for audit.

7. REPORT honestly.
   - Report baseline vs `results.best_config` delta for the agreed metrics, cost, token use, trial count, failed trials, and `results.stop_reason`.
   - Use `traigent-analyze-results` for `OptimizationResult` inspection and `show-significant-tuned-variables` to explain which knobs mattered.
   <!-- PROTECTED -->
   - If results are flat, noisy, failed, or negative, call it a no-boost result. Do not hide it or promote a winner that does not beat the baseline on the eval set.
   <!-- /PROTECTED -->
   - When wire-proofing against a Traigent backend, expect the run's
     configuration-record count to differ from `len(results.trials)` — the
     backend de-duplicates/aggregates repeated configs. Assert your claims
     (e.g. composite telemetry present) over the RETURNED records, and note
     that aggregate `results.total_cost` can be `None` even when per-trial
     cost measures are `0.0`.

<!-- PROTECTED -->
## Claim scope

- End-to-end optimization results are observations from the client's eval dataset and run conditions.
- Per-variable calibration certificates are the only procedural calibration claims; they do not certify future product behavior.
- Acceptable winner wording: `Calibration-backed winner (client-attested)`.
- Never say `guarantee`, never imply universal lift, and never present catalog recommendations as proof that the client agent will improve.
<!-- /PROTECTED -->

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
