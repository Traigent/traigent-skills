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

Two knob families exist and each is catalogued in exactly one place:

- **Domain-specific atomic knobs** (schema presence, retrieval strategy, generation path, few-shot
  policy, repair policy, and similar per-task value-picks) are catalogued here. `@traigent.optimize`'s
  `configuration_space` accepts any key you choose -- there is no fixed acceptance list -- but some
  names below are *also* proposed by the installed SDK's guidance catalog
  (`traigent/config_generator/catalog/tvar_catalog.v1.json`, traigent>=0.27.0), a set of
  measured/observational suggestions, not a required or exhaustive one: `schema_context`,
  `generation_path`, `fewshot_selector`, `fewshot_k`, `candidate_count`, `repair_policy` (text2SQL),
  and `retrieval_k` (RAG) all match a catalog entry name. `retriever`, `query_strategy`,
  `answer_path`, `example_organization`, and `self_consistency` below come from the TraigentDemo
  recipes, not the catalog -- no catalog entry proposes them under any agent type. `context_order`
  is a special case: the catalog *does* have a `rag.context_order.v1` entry by that name, but with a
  different value set (`relevance_desc`/`primacy_recency`/`question_then_evidence`/
  `key_evidence_edges`) than the recipe below uses (`as_retrieved`/`score_desc`/`score_asc`) -- treat
  them as two distinct value vocabularies sharing a name, not interchangeable.
- **Composite / control-flow patterns** are catalogued in `traigent-optimize-composite-knobs`'s
  `references/pattern-catalog.md` (factory signatures) and its `SKILL.md` (the Explorer-name-to-
  factory map) -- not restated here. They carry sub-parameters (an escalation margin, a cardinality,
  a judge stage) instead of a single value-pick, so read `candidate_count` and `self_consistency`
  below as the atomic, manually-wired form of the idea; use the composite factories when you want the
  calibrated, telemetry-emitting version (majority vote, judge-scored best-of-n, or a bounded retry
  loop).
- The public **Knob Explorer** (https://traigent.ai/#/knob-explorer) is the canonical public
  taxonomy customers see. Where an Explorer label has no counterpart in either the catalog or a
  recipe above, it is a naming proposal, not an available knob (see "Other domains" below for the
  full map).

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

### Other domains

The Knob Explorer also groups public knobs by classification/extraction, code/math, and web/GUI
agents. As of traigent>=0.27.0 the installed guidance catalog
(`traigent/config_generator/catalog/tvar_catalog.v1.json`) backs one more named family beyond the
text2SQL and RAG recipes above: a **code-editing** group. It shares the text2SQL family's
`code_gen` agent type in the catalog -- it is not a separate agent type -- but a different
`category` (`agent_computer_interface` instead of `structural`/`prompting`/`repair`/`generation`),
so treat it as a distinct knob family within the same agent type, not a separate domain.

```python
CODE_EDITING_STRUCTURAL_SPACE = {
    "repo_context_strategy": ["issue_locality_first", "focused_search", "call_graph_plus_tests", "repo_index"],
    "file_view_window": [50, 120, 400],
    "edit_granularity": ["minimal_patch", "function_scope", "file_scope", "multi_file_plan"],
    "test_selection_strategy": ["none", "focused_changed_files", "related_unit_tests", "full_regression_budgeted"],
    "patch_review_mode": ["off", "self_review", "diff_then_test_review", "reviewer_agent"],
}
```

| Knob | What it changes |
|---|---|
| `repo_context_strategy` | How the agent navigates the repository before editing (issue-linked files, targeted search, call-graph/test expansion, or a broader repo index). |
| `file_view_window` | How many lines of surrounding file context the agent sees per view. |
| `edit_granularity` | The size of the edit unit the agent may propose, from a minimal patch to a multi-file plan. |
| `test_selection_strategy` | Which tests run to validate a patch, from none to a budgeted full regression. |
| `patch_review_mode` | Whether and how the patch is reviewed (self-review, diff+test review, or a separate reviewer stage) before it is returned. |

The rest of the Explorer's public taxonomy has no counterpart in the installed guidance catalog or
in a recipe above yet. Full Explorer-id-to-taxonomy map for what is not already covered by the
text2SQL, RAG, or code-editing tables above:

| Explorer id | Domain | Maps to |
|---|---|---|
| `sql_guidance` | text2SQL | no counterpart yet (Explorer-only) |
| `value_retrieval` | text2SQL | no counterpart yet (Explorer-only) |
| grounding/abstention policy | RAG / multi-hop QA | no counterpart yet (Explorer-only) |
| rubric / label-definition hint | classification / extraction | no counterpart yet (Explorer-only) |
| ontology / taxonomy conformance | classification / extraction | no counterpart yet (Explorer-only) |
| execution-verified repair | code / math | maps to the composite `self_debug` factory (retry a stage until an external predicate passes) when the retry needs loop state, or to the atomic `repair_policy` knob above when a single fixed retry is enough -- pick based on whether you need calibrated loop state, not the label alone |
| program-aided reasoning (PAL) | code / math | no counterpart yet (Explorer-only) |
| `verifier_critic` | code / math | no counterpart yet (Explorer-only) |
| `observation_modality` | web / GUI agents | no counterpart yet (Explorer-only) |
| `action_space_modality` | web / GUI agents | no counterpart yet (Explorer-only) |
| domain idiom / style hint | code / writing | no counterpart yet (Explorer-only) |

The Explorer's own `schema_context` values (`ddl_fk`/`ddl_fk_rows`/`compact`/`m_schema`) are a
*third* value vocabulary, different from both the catalog's (`full_ddl_fk`/`linked_top6`/
`linked_top10`) and the text2SQL recipe's above (same three catalog values) -- do not assume the
Explorer's public value names are what the installed SDK takes.

Define any "no counterpart yet" row as an ordinary `configuration_space` entry using the same
topology-then-value pattern as the families above rather than treating an Explorer label as a
pre-verified SDK name, and run `traigent-analyze-guidance` against your own evaluator to see what the
catalog currently proposes for your agent type.

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
+    metric_functions={"accuracy": accuracy_metric},
 )
 async def fn(example):
     cfg = traigent.get_config()
+    # run_agent returns traigent.with_usage(answer, total_cost=call_cost_usd)
     return await run_agent(example, cfg)
 
-result = await fn.optimize(algorithm="grid", max_trials=1)
+result = await fn.optimize(
+    algorithm="random",
+    max_trials=80,
+)
+trials_df = result.to_dataframe()
```

The before state is useful only as a baseline:
`configuration_space={k:[baseline_v]}` and `objectives=["accuracy"]`. The after
state gives random search a full structural search space, keeps the baseline
explicit through `default_config=BASELINE`, optimizes both accuracy and cost,
records accuracy through a named `metric_functions` entry, and reads completed
trials from `result.to_dataframe()`. Cost comes from the function: `run_agent`
returns `traigent.with_usage(answer, total_cost=call_cost_usd)`, which reaches
the trial's `cost`, `results.total_cost` and the cost cap. `accuracy_metric` then
receives the wrapper dict, so it scores `output["text"]`. Do not register `cost`
in `metric_functions` or return it in a metrics dict: it is an evaluator-reserved
key and the value is dropped.

## Operational checklist

1. Confirm execution mode before a paid run: for connected real optimization, omit `algorithm` or use `algorithm="auto"` — the default connected path to real cloud Optuna TPE. Use `grid` and `random` only for explicit local/offline search. Named smart selectors like `tpe` (the Optuna/Bayesian family) execute on connected runs since 0.20.1 (see version-matrix: `smart-selector-exec`): on an authenticated connected run, supported names bind to the typed backend Optuna strategy; unsupported names (`nsga2`/`cmaes`) fail fast with a capability message (Traigent/Traigent#1752, #1758). They never run locally: `ConfigurationError` with `offline=True`, and the SDK's local optimizer registry rejects the name with `OptimizationError` (*"Smart optimization ('tpe') runs in the Traigent cloud and is not available in the local SDK (which supports 'grid' and 'random')"*). Installing Optuna (`traigent[integrations]`) does **not** make `tpe` resolve locally -- the only locally-registered algorithms are `grid` and `random` (`_LOCAL_ALGORITHMS = {grid, random}`). Use `algorithm="random"` only when you deliberately want local sampling for a large structural search space.
2. Set one approved cap for this run — `cost_limit=<approved USD>` on `.optimize()` or `TRAIGENT_RUN_COST_LIMIT` in the launching process, never in `.env` (litellm auto-loads it into every later run). Set `TRAIGENT_COST_APPROVED=true` only after the user approved that figure, and only in that process: it silences the SDK's own prompt, whose `[r]` key would set the cap to 1.5× the *estimate*.
3. A rerun over the same function and dataset repeats configurations by default (`cache_policy="allow_repeats"`); pass `cache_policy="prefer_new"` to skip ones already evaluated — and know that it can then stop early with fewer trials than `max_trials`.
4. Read trials from `result.to_dataframe()`, not from `custom_evaluator` callbacks.
5. Leave `timeout=` unset (the run-level default is no wall-clock cap). Bound a paid search by `max_trials` and the cost cap; a clock cut a 12-trial search at 7 in the field. Keep a per-request timeout inside your own LLM call instead.

## After the run

Use `traigent-analyze-variable-importance` to rank which structural knobs mattered.
Report results with honest task-local language: "on this fixed Spider slice" or
"on this HotpotQA slice," not as a universal causal claim.

Use `traigent-optimize-run` for `func.optimize()` parameters, cost handling,
stop reasons, parallel execution, and result-table display.
