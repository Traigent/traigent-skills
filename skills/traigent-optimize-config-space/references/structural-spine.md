# Structural Configuration Spine

Use this reference when turning an `@traigent.optimize` evaluator into an
optimizer by defining task-level knobs for text2SQL, RAG, multi-hop QA, schema
context, retrieval strategy, generation paths, few-shot policies,
self-consistency, repair policies, or cost-aware accuracy/cost objectives.

For typed parameter APIs, use `traigent-optimize-config-space`. For execution
details, budgets, timeouts, and result handling, use `traigent-optimize-run`.

## Core rule

Do not stop at naive prompt tuning.

Naive = one model + one prompt string:

```python
configuration_space = {
    "model": ["gpt-4o-mini", "gpt-4o"],
    "prompt_template": [BASE_PROMPT, STRICT_PROMPT],
}
```

Structural = a task spine whose knobs change what the agent can see, how it
reasons, how many candidates it samples, and how it recovers from errors:

```python
configuration_space = {
    "schema_context": ["none", "full", "linked"],
    "generation_path": ["direct", "plan-CoT", "decompose"],
    "fewshot_k": [0, 3, 5],
    "fewshot_selector": ["random", "masked-similarity", "DAIL"],
    "example_organization": ["flat", "schema-grouped", "difficulty-ramped"],
    "candidate_count": [1, 3, 5],
    "repair_policy": ["none", "syntax", "execution"],
}
```

Structural knobs carry the gains because they change the optimization problem
itself. Schema presence and retrieval structure decide whether the agent has the
evidence it needs. Few-shot examples often help only after schema or retrieved
context is present. Self-consistency can help multi-hop QA, while it may be flat
on a strong SQL default. The optimizer should adapt the winning configuration to
the task instead of forcing one global recipe.

## Structural knob taxonomy

### text2SQL

Use this family for the TraigentDemo path:
`demos/TraigentDemo/examples/use-cases/text2sql-sota-optimizer`.

```python
BASELINE = {  # the honest naive strawman: no schema, no structure
    "schema_context": "none",
    "generation_path": "direct_dail",
    "fewshot_k": 0,
    "fewshot_selector": "random",
    "example_organization": "sql_only",
    "candidate_count": 1,
    "repair_policy": "off",
}

TEXT2SQL_STRUCTURAL_SPACE = {
    "schema_context": ["none", "full_ddl_fk", "linked_top6", "linked_top10"],
    "generation_path": ["direct_dail", "query_plan_cot", "divide_conquer_cot"],
    "fewshot_k": [0, 1, 3, 5],
    "fewshot_selector": ["random", "masked_question_similarity", "dail_selection"],
    "example_organization": ["full_info", "sql_only", "dail_qa_sql"],
    "candidate_count": [1, 2, 3],
    "repair_policy": ["off", "sqlite_error_once", "sqlite_error_or_empty_once"],
}
```

| Knob | What it changes |
|---|---|
| `schema_context` | Whether the model sees no schema, the full schema, or linked schema fragments. |
| `generation_path` | Whether SQL is generated directly, via planning/CoT, or by decomposing the question. |
| `fewshot_k` | How many examples are included. |
| `fewshot_selector` | Whether examples are random, masked-similarity selected, or DAIL-style selected. |
| `example_organization` | How examples are ordered or grouped before generation. |
| `candidate_count` | Self-consistency count for generating and selecting among candidate SQL queries. |
| `repair_policy` | Whether to repair syntax failures or execution failures before scoring. |

### RAG Multi-Hop QA

Use this family for the TraigentDemo path:
`demos/TraigentDemo/examples/use-cases/hotpotqa-rag-optimizer`.

```python
BASELINE = {  # naive: one paragraph, direct answer, no voting
    "retriever": "first_paragraph",
    "retrieval_k": 1,
    "query_strategy": "single_hop",
    "context_order": "as_retrieved",
    "answer_path": "direct",
    "fewshot_k": 0,
    "self_consistency": 1,
}

RAG_STRUCTURAL_SPACE = {
    "retriever": ["first_paragraph", "bm25_question", "bm25_title_question"],
    "retrieval_k": [1, 2, 3, 5],
    "query_strategy": ["single_hop", "decompose_bridge"],
    "context_order": ["as_retrieved", "score_desc", "score_asc"],
    "answer_path": ["direct", "extract_then_answer", "cot_then_answer"],
    "fewshot_k": [0, 1, 2],
    "self_consistency": [1, 3],
}
```

| Knob | What it changes |
|---|---|
| `retriever` | Whether context comes from a fixed first-pass retriever or BM25. |
| `retrieval_k` | How many passages are available to the answerer. |
| `query_strategy` | Whether retrieval uses the original question or decomposes bridge/entity hops. |
| `context_order` | Whether evidence is presented as retrieved, by score descending, or by score ascending (lost-in-the-middle test). |
| `answer_path` | Whether the answerer responds directly, extracts evidence first, or uses CoT. |
| `fewshot_k` | How many multi-hop exemplars are supplied. |
| `self_consistency` | How many answer candidates are sampled before selection. |

## Evaluator to optimizer

Transform the decorator from a frozen evaluator into a real optimizer.

```diff
 @traigent.optimize(
     eval_dataset=EVAL_DATASET,
-    configuration_space={k: [baseline_v] for k, baseline_v in BASELINE.items()},
-    objectives=["accuracy"],
+    configuration_space=STRUCTURAL_SPACE,
+    default_config=BASELINE,
+    objectives=["accuracy", "cost"],
+    metric_functions={
+        "accuracy": accuracy_metric,
+        "cost": cost_metric,
+    },
 )
 async def fn(example):
     cfg = traigent.get_config()
     return await run_agent(example, cfg)
 
-result = await fn.optimize(algorithm="grid", max_trials=1)
+result = await fn.optimize(
+    algorithm="random",
+    max_trials=80,
+    timeout=1800.0,
+)
+trials_df = result.to_dataframe()
```

The before state is useful only as a baseline:
`configuration_space={k:[baseline_v]}` and `objectives=["accuracy"]`. The after
state gives random search a full structural search space, keeps the baseline
explicit through `default_config=BASELINE`, optimizes both accuracy and cost,
records metrics through named `metric_functions`, and reads completed trials
from `result.to_dataframe()`.

## Operational checklist

1. Confirm execution mode before a paid run: for connected real optimization, omit `algorithm` or use `algorithm="auto"`; in SDK 0.20.0 this is the reliable path to real cloud Optuna TPE. Use `grid` and `random` only for explicit local/offline search. Smarter selector names like `tpe` (the Optuna/Bayesian family) validate as known names but are **not yet executable end-to-end** -- a `tpe` run fails before any trial starts (`ConfigurationError` with `offline=True`; the SDK's local optimizer registry likewise rejects the name with `OptimizationError`: *"Smart optimization ('tpe') runs in the Traigent cloud and is not available in the local SDK (which supports 'grid' and 'random')"*), and connected typed runs self-abort before backend guidance because the SDK does not execute/transmit the named selector (Traigent/Traigent#1752). Installing Optuna (`traigent[integrations]`) does **not** make `tpe` resolve -- the only locally-registered algorithms are `grid` and `random` (`_LOCAL_ALGORITHMS = {grid, random}`). Use `algorithm="random"` only when you deliberately want local sampling for a large structural search space.
2. Set `TRAIGENT_COST_APPROVED=true` and a high `TRAIGENT_RUN_COST_LIMIT`; rely on your own real-usage budget guard.
3. Use a fresh per-run study directory. A persistent study dedups configs and can stop early.
4. Read trials from `result.to_dataframe()`, not from `custom_evaluator` callbacks.
5. Pass a large `timeout=` to `.optimize()`. The default 60s can silently truncate real runs.

## After the run

Use `traigent-analyze-variable-importance` to rank which structural knobs mattered.
Report results with honest task-local language: "on this fixed Spider slice" or
"on this HotpotQA slice," not as a universal causal claim.

Use `traigent-optimize-run` for `func.optimize()` parameters, cost handling,
stop reasons, parallel execution, and result-table display.
