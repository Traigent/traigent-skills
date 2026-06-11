# Instrument Recipe

This reference shows the smallest useful Python diff: keep the existing agent function, add Traigent around it, pull TVARs from recommendations, add one composite, return `(output, metrics)`.

## Before

```python
from openai import OpenAI

client = OpenAI()


def answer_question(question: str) -> str:
    context = retrieve_context(question, k=4)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Answer using the provided context."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )
    return response.choices[0].message.content
```

## After

```python
from time import perf_counter

import traigent
from openai import OpenAI
from traigent.api.decorators import EvaluationOptions
from traigent.config_generator.recommendations import (
    RECOMMENDATION_CAVEAT,
    recommend_configuration_space,
)
from traigent.knobs.patterns import self_consistency
from traigent.knobs.runtime import StageRunner, execute_composite
from traigent.knobs.telemetry import merge_composite_measures

client = OpenAI()

RAG_RECOMMENDATIONS = recommend_configuration_space("rag", min_impact="low")
print(RAG_RECOMMENDATIONS["caveat"] or RECOMMENDATION_CAVEAT)

CONSISTENCY = self_consistency(
    "qa_self_consistency",
    stage="answer",
    cardinality="candidate_count",
    stage_tuned_params=(
        "model",
        "temperature",
        "retrieval_k",
        "context_selection_policy",
        "context_order",
    ),
)

CONFIGURATION_SPACE = {
    **RAG_RECOMMENDATIONS["configuration_space"],
    "model": ["gpt-4o-mini", "gpt-4o"],
    "temperature": [0.0, 0.2, 0.7],
    "candidate_count": [1, 2, 3],
    **CONSISTENCY.members,
}


def _normalize_answer(answer: str) -> str:
    return answer.strip().lower()


def _render_context(question: str, cfg: dict) -> str:
    # Wire catalog TVARs into existing retrieval/context code.
    k = int(cfg.get("retrieval_k", 4))
    chunks = retrieve_context(
        question,
        k=k,
        policy=cfg.get("context_selection_policy", "similarity"),
        order=cfg.get("context_order", "relevance_desc"),
    )
    return format_context(
        chunks,
        summary_style=cfg.get("summary_style", "none"),
        compression_ratio=float(cfg.get("compression_ratio", 1.0)),
        citation_policy=cfg.get("citation_policy", "none"),
    )


def _call_answer_model(question: str, cfg: dict) -> str:
    context = _render_context(question, cfg)
    response = client.chat.completions.create(
        model=cfg["model"],
        temperature=float(cfg["temperature"]),
        messages=[
            {"role": "system", "content": "Answer using the provided context."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )
    return response.choices[0].message.content


@traigent.optimize(
    evaluation=EvaluationOptions(
        # Built-in evaluator: expected outputs live in the JSONL rows and are
        # exact-matched against the function's output. With the composite
        # (output, metrics) tuple return, USE THE BUILT-IN EVALUATOR — a custom
        # `scoring_function` (and 3-arg `metric_functions`) is currently NOT
        # invoked with the unpacked prediction on this path and every trial
        # silently scores accuracy=0.0 (known SDK issue). If you see uniform
        # zero accuracy alongside a sane built-in `score`, suspect this wiring,
        # not your agent.
        eval_dataset="evals/qa.jsonl",
    ),
    objectives=["accuracy", "cost"],
    configuration_space=CONFIGURATION_SPACE,
    execution_mode="hybrid",
)
def answer_question(question: str):
    cfg = dict(traigent.get_config())
    candidate_count = int(cfg["candidate_count"])
    started = perf_counter()

    def run_answer(_item: dict) -> list[str]:
        return [_call_answer_model(question, cfg) for _ in range(candidate_count)]

    run = execute_composite(
        CONSISTENCY.structure,
        {
            "answer": StageRunner(
                run=run_answer,
                key_fn=_normalize_answer,
                samples=candidate_count,
            )
        },
        config=cfg,
        calibrated_values={},
    )

    output = "" if run.result_kind.value != "output" else str(run.output)
    metrics: dict[str, float] = {
        "latency_ms": (perf_counter() - started) * 1000.0,
        "cost": estimate_last_call_cost_usd(),
    }
    merge_composite_measures(metrics, run)
    return output, metrics
```

Notes:

- `execute_composite(..., config=cfg, ...)` passes the config mapping as the item to stage runners. Close over the original function input, as shown with `question`.
- The two-item tuple is intentional: the evaluator sees `output`, and numeric `metrics` ride the measures channel.
- If production code must keep returning `str`, keep this optimized function as the eval surface and expose `def answer_question_plain(question: str) -> str: return answer_question(question)[0]` only where needed.
- The helper functions `retrieve_context`, `format_context`, and `estimate_last_call_cost_usd` are application code, not Traigent APIs.

## Environment

Development/mock mode:

```bash
export TRAIGENT_OFFLINE_MODE=true
```

```python
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
```

Real optimization:

```bash
export TRAIGENT_API_KEY=...
export TRAIGENT_BACKEND_URL=...
export OPENAI_API_KEY=...
export TRAIGENT_RUN_COST_LIMIT=5.00
```

Use `TRAIGENT_BACKEND_URL` only when the client has a non-default backend endpoint. Provider keys depend on the models in the config space.

## Dataset gotchas (operational)

- **The evaluation dataset file is validated at DECORATION (import) time**, not at
  `optimize()` time. Write/generate the JSONL before the module defining the
  decorated function is imported, or import fails with a path
  `ValidationError`.
- **Hybrid mode enforces dataset path containment**: the dataset file must
  reside under the SDK working directory of the process running the
  optimization. Offline/mock runs accept absolute paths anywhere; the hybrid
  run rejects them. Keep the JSONL in a scratch dir under the project root
  (e.g. `.boost-scratch/tickets.jsonl`).

## Per-shape variations

| Shape | Change from the example |
|---|---|
| Single LLM call | Keep `self_consistency`, or switch to `best_of_n` when a judge stage returns finite numeric scores. |
| Cheap-vs-expensive | Use `binary_cascade`; create `cheap` and `strong` stage runners and calibrate/pass the margin threshold. |
| Multi-stage chain | Use `n_cascade`; map each stage name to the existing stage function and keep one threshold per non-terminal stage. |
| Router | Use `router`; provide signal functions over input features and keep terminal arms ungated. |
| Tool loop | Use `react_tool_loop` with `LoopBodyRunner`; keep `max_tool_calls` literal and pass `tool_confidence_min` as a calibrated value. |
| Generate-then-check | Use `verification_gate`; wire the verifier signal and include verifier style/model/question count knobs in the config space. |
| Specialists | Use `moe`; each expert is a stage, with `aggregate="vote"` or `aggregate="judge"`. |
| Primary plus backup | Use `fallback`; model no-accept or low-margin backup behavior, not provider exceptions. |
| Iterative refine | Use `self_refine` or the `bounded_refine_loop` recipe from `traigent-composite-knobs/references/advanced-recipes.md`. |
