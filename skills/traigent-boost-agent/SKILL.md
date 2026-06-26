---
name: traigent-boost-agent
description: "End-to-end 12-step lifecycle playbook for adding Traigent to an existing client agent codebase and measurably boosting accuracy, cost, latency, or reliability. Use when asked to add Traigent to this agent, onboard this agent to Traigent end-to-end, run a full agent-build lifecycle, wire an evaluator and optimize, boost accuracy/cost of an existing agent codebase, select TVARs with recommend_configuration_space(), choose composite knobs by agent shape, instrument @traigent.optimize minimally, validate in mock mode, run real optimization with budgets, inspect results, iterate, or gate a promoted config."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "2.0.1"
---

# Traigent Boost Agent

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

## The 12-Step Lifecycle Playbook

1. ANALYZE the client codebase before writing code.
   - Find LLM call sites, prompt construction, retrieval steps, tool loops, validators, judges, retries, and postprocessors.
   - Useful greps: raw SDK calls (`chat.completions.create`, `responses.create`, `messages.create`), framework calls (`ChatOpenAI`, `ChatAnthropic`, `Runnable`, `AgentExecutor`, `create_react_agent`, `litellm.completion`), retrieval (`similarity_search`, `as_retriever`, `rerank`), and loop/control terms (`tool_calls`, `function_call`, `critic`, `judge`, `repair`, `retry`).
   - Identify the agent SHAPE: single LLM call, cheap-vs-expensive model path, multi-stage chain, input router, tool loop, generate-then-check, specialists, fallback, or iterative refinement.
   - Pick the smallest function enclosing the scoreable agent behavior. Do not decorate an app route, auth layer, retry wrapper, or generic provider client if the actual input/output to evaluate is higher level.
   - Use `references/codebase-analysis.md` for grep patterns, shape markers, and codebase-specific evidence mining.

2. CURATE the evaluation dataset.
   - Start from existing fixtures, golden sets, accepted traces, support tickets, or redacted logs before synthesizing new examples.
   - Keep tuning and holdout slices separate, stratify by known input classes, and report sample count, source, label quality, and exclusions.
   - Use JSONL with scoreable `input` and `output` fields when a built-in evaluator can score the task.
   - Mock/offline-check a tiny slice before any backend generation or paid provider work.
   - DELEGATE: `traigent-curate-dataset` owns dataset recipes, growth, example scoring, and quality loops.

3. CHOOSE the metric.
   - Decide what "good" means before writing optimizer code: task success, correctness, cost, latency, safety, reliability, or a measured combination.
   - Prefer built-in objective names when they match the product decision; use custom metric functions only when domain logic is checkable and necessary.
   - Treat must-not-violate behavior as a safety constraint or promotion gate, not as an ordinary objective to trade away.
   - DELEGATE: `traigent-choose-metric` owns the metric interview and objective vocabulary.

4. WIRE OR BUILD the evaluator.
   - Use the wire-first ladder: `eval_dataset` -> `scoring_function` -> `metric_functions` -> `custom_evaluator` -> `BaseEvaluator`.
   - Start deterministic when the task has ground truth or checkable domain logic; use LLM judges only when deterministic scoring cannot express the quality target.
   - Audit any LLM judge before trusting it to drive optimization.
   - DELEGATE: `traigent-build-evaluator` owns evaluator code; `traigent-evaluator-audit` owns judge reliability checks.

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
   - For range syntax, constraints, and typed parameters, cross-reference `traigent-configuration-space` instead of duplicating it.
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

   - For exact factory signatures, `StageRunner`/`LoopBodyRunner` wiring, `execute_composite`, and telemetry, cross-reference `traigent-composite-knobs`; do not duplicate its catalog.
   - DELEGATE: `traigent-composite-knobs` owns composite factory details and runtime wiring.

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
   - Cross-reference `traigent-quickstart` and `traigent-debugging` for mock/offline setup.
   - Use `from traigent.testing import enable_mock_mode_for_quickstart` plus `TRAIGENT_OFFLINE_MODE=true` for keyless development.
   - Confirm dataset loading, config sampling, stage wiring, tuple-return unpacking, and zero failed trials before real provider calls.
   - DELEGATE: `traigent-quickstart` owns first-run setup; `traigent-debugging` owns mock/offline failure diagnosis.

9. OPTIMIZE for real only with cost limits and explicit approval.
   - Cross-reference `traigent-run-optimization` for `func.optimize()`, `optimize_sync()`, algorithms, `max_trials`, parallelism, and `CostLimitExceeded`.
   - Set an explicit `TRAIGENT_RUN_COST_LIMIT` and verify provider keys before the real run. If a Traigent backend is used, set `TRAIGENT_API_KEY` and `TRAIGENT_BACKEND_URL` as appropriate for the client environment. See [Getting your Traigent API key](../traigent-quickstart/SKILL.md#get-your-traigent-api-key) if you have not yet obtained `TRAIGENT_API_KEY`.
   - Present a cost estimate and get the user's explicit approval before any paid run.
   - Start with a bounded trial budget, keep the current production baseline in the search space, and save results artifacts for audit.
   - DELEGATE: `traigent-run-optimization` owns algorithms, budgets, and execution controls.

10. INSIGHT: configurations AND examples.
   - Configuration side: start with `get_optimization_insights(results)`, then use `show-significant-tuned-variables` for importance-backed knob ranking.
   - Example side: use `ExampleInsightsClient` to compute example scores, read scores, and read dataset-quality metadata. Its reportable scope is non-signal metadata; do not claim hidden difficulty, informativeness, ambiguity, or causal signal values.
   - Report baseline vs `results.best_config` delta for the agreed metrics, cost, token use, trial count, failed trials, and `results.stop_reason`.
   - Use `traigent-analyze-results` for `OptimizationResult` inspection and `show-significant-tuned-variables` to explain which knobs mattered.
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
   - DELEGATE: `traigent-analyze-results` owns result-object depth; `show-significant-tuned-variables` owns richer TVAR importance reporting.

11. RECOMMEND the most promising next steps.
   - Point at the symptom-to-action table in `references/insights-and-iteration.md` and choose one next hypothesis, not a bundle of unrelated changes.
   - Use example-side findings only as evidence for targeted curation or heldout checks.
   - Planned: a backend next-steps endpoint may eventually package these recommendations; until then, use the manual symptom-to-action table.
   - DELEGATE: `traigent-iterate` owns post-run next-action selection.

12. COMPLETE: recommend the safety gate and CI checks.
   - Use in-run `safety_constraints` for must-not-violate trial filters.
   - Use `PromotionGate` for candidate-vs-incumbent decisions on the same holdout.
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
