# Composite Advanced Recipes

These are recipe specializations over catalog factories, not new algebra.

## `adaptive_rag_gate`

Use `router` for adaptive RAG dispatch. Route on adequacy for the light arm, not raw hardness: the light arm should run when `query_light_adequacy(question) >= threshold`; the heavy terminal arm handles abstention or fall-through.

The recipe from `router_example.py`:

```python
ADAPTIVE_RAG_GATE = router(
    "adaptive_rag_gate",
    arms=("rag_light", "rag_heavy"),
    signals=("query_light_adequacy",),
    thresholds=(COMPLEXITY_THRESHOLD,),
    signal_inputs=(("question",),),
    tuned_params=(
        ("retrieval_mode", "query_complexity_strategy", "retrieval_k"),
        (
            "retrieval_mode",
            "query_complexity_strategy",
            "retrieval_k",
            "reranker",
            "web_fallback",
            "decompose_query",
        ),
    ),
)
```

Calibration notes:

- Calibrate `COMPLEXITY_THRESHOLD` against the same `question` input surface declared in `signal_inputs`.
- Treat `retrieval_confidence_min` as a heavy-arm CVAR owned by `rag_heavy`; the outer router does not consume it unless the heavy arm is modeled as a nested composite.
- Use router telemetry: `route_selected`, `dispatch_signal_margin`, `gate_signal_adequate`.

## `bounded_refine_loop`

Use `self_refine` for a bounded repair/refinement loop. The loop has one acceptance-direction signal threshold and a literal iteration envelope.

The recipe from `verification_gate_example.py`:

```python
BOUNDED_REFINE_RECIPE = self_refine(
    name="bounded_refine_loop",
    stage="critique_repair",
    signal="refine_accept_score",
    threshold="acceptance_threshold",
    max_iters=3,
    state_keys=(
        "draft",
        "critique",
        "score",
        "previous_score",
        "improvement_delta",
        "round",
    ),
    signal_inputs=("draft", "score", "previous_score", "improvement_delta"),
    stage_tuned_params=(
        "critic_model",
        "feedback_rubric",
        "repair_prompt",
        "max_repair_rounds",
        "stop_condition",
    ),
)
```

Calibration notes:

- Calibrate `acceptance_threshold` for the `refine_accept_score` signal.
- Thread `previous_score` and `improvement_delta` through loop state when the body can compute them.
- `max_iters` is literal. `max_repair_rounds` may be a stage parameter, but the current loop IR does not make the structural loop bound tunable.
- A simultaneous raw `improvement_min_delta` stop is not expressible in v1.

## Deferred

- `mixture_of_agents` V1.5 is deferred as a distinct recipe surface. Use `moe` for the v1 committee form when each expert contributes one candidate and aggregation is majority vote or judge max.
- `deliberative_search` and Tree-of-Thought style branching need new algebra. Do not model them as `self_refine` unless the search is honestly linear threaded-state refinement.
