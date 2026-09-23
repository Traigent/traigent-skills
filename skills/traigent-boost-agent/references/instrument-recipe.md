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

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.config_generator import generate_config
from traigent.knobs.patterns import self_consistency
from traigent.knobs.runtime import StageRunner, execute_composite
from traigent.knobs.telemetry import merge_composite_measures

# Reads the target file and proposes tuned variables from the shipped TVar
# catalog. enrich=False keeps it offline: no LLM call, no spend.
SUGGESTED = generate_config(__file__, function_name="answer_question", enrich=False)
for rec in SUGGESTED.recommendations:
    # Rows are search-space STARTING POINTS, not performance claims -- say so to
    # the user. apply_guidance carries the manual runtime steps where a knob
    # needs them (the coding / RAG knob packs do).
    print(f"{rec.name}: {rec.range_type} (impact {rec.impact_estimate}) -- {rec.reasoning}")
    if rec.apply_guidance:
        print(f"  apply: {rec.apply_guidance}")

CONSISTENCY = self_consistency(
    "qa_self_consistency",
    stage="answer",
    cardinality="candidate_count",
    stage_tuned_params=("model", "temperature", "retrieval_k"),
)

# generate_config returns ROWS, not a ready configuration_space dict. Build the
# space only from rows the function below actually reads -- a declared knob the
# function never reads is a silent no-op that still multiplies the search. Each
# row carries range_type and range_kwargs (e.g. Choices -> {"values": [...]},
# IntRange -> {"low":, "high":}). Take Choices rows literally; convert numeric
# ranges with Range/IntRange from traigent, and read apply_guidance first for
# knobs that need runtime wiring. Add a name to WIRED only after wiring it.
WIRED = {"context_selection_policy", "context_order", "summary_style", "citation_policy"}

SUGGESTED_CHOICES = {
    rec.name: rec.range_kwargs["values"]
    for rec in SUGGESTED.recommendations
    if rec.range_type == "Choices" and rec.name in WIRED
}

CONFIGURATION_SPACE = {
    **SUGGESTED_CHOICES,
    "model": ["gpt-4o-mini", "gpt-4o"],
    "temperature": [0.0, 0.2, 0.7],
    "candidate_count": [1, 2, 3],
    "retrieval_k": [2, 4, 8],
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
    # litellm.completion, not a raw provider client: mock mode intercepts only
    # LiteLLM/LangChain calls, so the dry-run below stays keyless and free.
    response = litellm.completion(
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
        # exact-matched against the function's unpacked `output`. A custom
        # scoring_function / metric_functions also receives the unpacked output.
        eval_dataset="evals/qa.jsonl",
    ),
    objectives=["accuracy", "cost"],
    configuration_space=CONFIGURATION_SPACE,
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

    if run.result_kind.value != "output":
        # A composite with no answer is a FAILED example, not an empty answer:
        # returning "" would let a run where every model call failed pass as green.
        raise RuntimeError(f"composite produced no output: {run.result_kind.value}")
    output = str(run.output)
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
export LITELLM_LOCAL_MODEL_COST_MAP=true   # stops LiteLLM's import-time pricing fetch
```

```python
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()
```

> Mock mode covers LiteLLM/LangChain calls only — a raw `openai` / `anthropic` client in the body makes real, billable calls even during a "keyless" mock dry-run. The After block calls `litellm.completion` for that reason; if you keep your own client, stub it for the dry-run.

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
- **Every run enforces dataset path containment**, offline or connected: the
  file must sit under the working directory of the optimizing process, or under
  `TRAIGENT_DATASET_ROOT`. An absolute path elsewhere is accepted at decoration
  and rejected when the run loads the dataset (`Dataset path must reside under
  …`). Keep the JSONL under the project root (e.g. `.boost-scratch/tickets.jsonl`)
  and run from that root.

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
| Iterative refine | Use `self_refine` or the `bounded_refine_loop` recipe from `traigent-optimize-composite-knobs/references/advanced-recipes.md`. |
