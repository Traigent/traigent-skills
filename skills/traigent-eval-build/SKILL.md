---
name: traigent-eval-build
description: "Build Traigent evaluators and scoring code. Use when wiring eval_dataset, scoring_function, metric_functions, custom_evaluator, ExampleResult, BaseEvaluator subclasses, deterministic checks, LLM judges, statistical repeated evaluations, hybrid evaluators, or fixing tuple-return/custom-scorer pitfalls."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.7"
---

# Traigent Build Evaluator

## When to Use

Use this skill after the metric is chosen and the user needs concrete evaluator code.

- For metric selection first, use `traigent-eval-choose-metric`.
- Mock/offline check before paid runs with `TRAIGENT_OFFLINE_MODE`, `enable_mock_mode_for_quickstart()`, and a tiny local dataset.
- Ask for explicit approval and set `TRAIGENT_RUN_COST_LIMIT` before any evaluator calls paid LLMs or backend services.
- Disjointness invariant: any slice used to tune a threshold, rubric, or metric must be disjoint from the holdout used to claim the result (see `traigent-eval-audit`). The example dataset paths below stand for your *tuning* slice.
- For full templates by method, read `references/evaluator-templates.md`.

## Wire-first decision ladder

Prefer the smallest evaluator surface that measures the chosen objective.

| Tier | Wire | Exact signature | Enough when |
|---|---|---|---|
| 1 | `eval_dataset` only | path/list/`Dataset` | Built-in metrics such as `accuracy`, `success_rate`, `error_rate`, `avg_output_length`, `cost`, or `latency` match the task. |
| 2 | `scoring_function` | `scoring_function(output, expected) -> float` | One numeric score per example is enough. |
| 3 | `metric_functions` | `{name: (output, expected, input_data) -> float}` | Multiple named metrics or input-aware checks are needed. |
| 4 | `custom_evaluator` | `custom_evaluator(func, config, example) -> ExampleResult` | The evaluator must call the function itself, collect timing/cost, run a judge, repeat samples, or fail closed. |
| 5 | `BaseEvaluator` subclass | `async evaluate(self, func, config, dataset, *, sample_lease=None, progress_callback=None) -> EvaluationResult` | You need full batch control, custom concurrency, leases, progress callbacks, or a reusable evaluator class. |

**No `expected_output` at all?** Tiers 1-3 assume a gold label to compare against. For
subjective/generative tasks with no labels, skip straight to Tier 4 with the **"LLM judge with
rubric, strict parse, and cost guardrails"** template in `references/evaluator-templates.md` —
and treat `traigent-eval-audit` as mandatory, because the judge owns the whole quality
signal (see `traigent-eval-choose-metric` → "The no-gold track").

### Tier 2: scoring function

```python
import traigent
from traigent.api.decorators import EvaluationOptions

def exact_match_score(output, expected) -> float:
    return 1.0 if str(output).strip() == str(expected).strip() else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/qa.jsonl",
        scoring_function=exact_match_score,
    ),
    objectives=["accuracy"],
    configuration_space={"temperature": [0.0, 0.3]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    import litellm  # pip install traigent[integrations]
    resp = litellm.completion(model=cfg.get("model", "gpt-4o-mini"), temperature=cfg["temperature"],
                              messages=[{"role": "user", "content": question}])
    return resp.choices[0].message.content
```

### Tier 3: metric functions

```python
import json

import traigent
from traigent.api.decorators import EvaluationOptions

def valid_json_metric(output, expected, input_data) -> float:
    try:
        json.loads(output)
    except json.JSONDecodeError:
        return 0.0
    return 1.0

def expected_field_metric(output, expected, input_data) -> float:
    # Guard the parse AND the access: model output may not be valid JSON,
    # and `expected` may be a scalar — both must score 0.0, not raise.
    try:
        data = json.loads(output)
        return 1.0 if data.get("label") == expected.get("label") else 0.0
    except (json.JSONDecodeError, AttributeError, TypeError):
        return 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/extraction.jsonl",
        metric_functions={
            "valid_json": valid_json_metric,
            "label_accuracy": expected_field_metric,
        },
    ),
    objectives=["label_accuracy", "valid_json"],
    configuration_space={"temperature": [0.0, 0.2]},
)
def extract(text: str) -> str:
    cfg = traigent.get_config()
    import litellm  # pip install traigent[integrations]
    resp = litellm.completion(model=cfg.get("model", "gpt-4o-mini"), temperature=cfg["temperature"],
                              messages=[{"role": "user", "content": text}])
    return resp.choices[0].message.content
```

#### Binding a per-example side field (e.g. `db_path`) — name a `metadata` parameter

`metric_functions` binds its arguments **by parameter name**, not by position (SDK
`evaluators/local.py` `_build_metric_keyword_arguments`). The names available are:
`output`/`expected` (the row's prediction + gold), `input_data` (the **nested `input` dict only**),
`metadata` (the row's top-level extras), `config`, `example`, and `example_index`.

For optional `surrogate_evaluator` mechanics and caveats, see `traigent-setup-decorator` -> "Evaluation Setup".

The documented `(output, expected, input_data)` signature **cannot** see a top-level side field like
`db_path` — `input_data` is only the `input` dict. To reach it, **name a `metadata` parameter** and
read the key the dataset contract routed there (see `traigent-dataset-curate` for the row mapping):

```python
from text2sql.execaccuracy import execution_accuracy  # opens metadata["db_path"], runs pred vs gold

def exec_acc(output, expected, metadata) -> float:   # NAME the param `metadata`
    return execution_accuracy(output, expected["sql"], metadata["db_path"])

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/salesco_30.jsonl",        # rows: {"input": {...}, "output": {"sql": "<gold>"}, "db_path": "..."}
        metric_functions={"exec_acc": exec_acc},     # Tier 3 — no climb to Tier 4/5 needed
    ),
    objectives=["exec_acc"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def to_sql(question: str, schema: str = "", db_id: str = "") -> str:
    ...
```

A param named `input_data` would receive the nested `input` dict, **not** `db_path` — that is the
silent trap. (Tier-4/5 alternative: read `example.metadata["db_path"]` directly inside a
`custom_evaluator` / `BaseEvaluator`.)

### Tier 4: custom evaluator

```python
import time

import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.api.types import ExampleResult

def evaluate_answer(func, config, example) -> ExampleResult:
    started = time.perf_counter()
    try:
        prediction = func(**example.input_data)
        score = 1.0 if str(prediction).strip() == str(example.expected_output).strip() else 0.0
        error_message = None
        success = True
    except Exception as exc:
        prediction = None
        score = 0.0
        error_message = str(exc)
        success = False

    return ExampleResult(
        example_id=str(example.metadata.get("id", "unknown")),
        input_data=example.input_data,
        expected_output=example.expected_output,
        actual_output=prediction,
        metrics={"accuracy": score},
        execution_time=time.perf_counter() - started,
        success=success,
        error_message=error_message,
        metadata={"method": "deterministic_exact_match"},
    )

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/qa.jsonl",
        custom_evaluator=evaluate_answer,
    ),
    objectives=["accuracy"],
    configuration_space={"temperature": [0.0, 0.3]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    import litellm  # pip install traigent[integrations]
    resp = litellm.completion(model=cfg.get("model", "gpt-4o-mini"), temperature=cfg["temperature"],
                              messages=[{"role": "user", "content": question}])
    return resp.choices[0].message.content
```

### Tier 5: BaseEvaluator subclass

```python
import time
from typing import Any

from traigent.api.types import ExampleResult
from traigent.evaluators import BaseEvaluator, Dataset
from traigent.evaluators.base import EvaluationResult

class ExactMatchEvaluator(BaseEvaluator):
    async def evaluate(
        self,
        func,
        config: dict[str, Any],
        dataset: Dataset,
        *,
        sample_lease=None,
        progress_callback=None,
    ) -> EvaluationResult:
        results = []
        started = time.perf_counter()

        for index, example in enumerate(dataset):
            prediction = func(**example.input_data)
            score = 1.0 if str(prediction).strip() == str(example.expected_output).strip() else 0.0
            result = ExampleResult(
                example_id=str(example.metadata.get("id", index)),
                input_data=example.input_data,
                expected_output=example.expected_output,
                actual_output=prediction,
                metrics={"accuracy": score},
                execution_time=0.0,
                success=True,
                metadata={"method": "exact_match"},
            )
            results.append(result)
            if progress_callback is not None:
                progress_callback(index, {"accuracy": score})

        accuracy = sum(r.metrics["accuracy"] for r in results) / len(results) if results else 0.0
        return EvaluationResult(
            config=config,
            example_results=results,
            aggregated_metrics={"accuracy": accuracy},
            total_examples=len(results),
            successful_examples=len(results),
            duration=time.perf_counter() - started,
        )
```

## The EvaluationExample input contract

The `example` argument passed to `custom_evaluator(func, config, example)` is an `EvaluationExample` object — not a dict.

| Attribute | Source in JSONL | Type | Notes |
|---|---|---|---|
| `example.input_data` | `"input"` key | `dict` | Expand as `func(**example.input_data)` to call the decorated function. |
| `example.expected_output` | `"output"` key | `Any` | Gold label; string, dict, or list depending on dataset. |
| `example.metadata` | All other keys | `dict` | Extra JSONL fields land here — `db_id`, `id`, `difficulty`, etc. |

**Common pitfalls:**
- `example["input"]` → `TypeError: 'EvaluationExample' object is not subscriptable`. Use `.input_data`, not dict access.
- `example.input` does not exist — the attribute is `.input_data` (name differs from the JSONL key).
- `example.output` does not exist — use `.expected_output`.
- Extra JSONL keys (e.g. `db_id`) are in `example.metadata["db_id"]`, not top-level attributes.

## The ExampleResult contract

On `traigent` 0.12.0+ (including the current SDK), construct `ExampleResult` with these fields (0.14+ adds one optional field, `user_metrics`):

| Field | Required | Meaning |
|---|---|---|
| `example_id` | yes | Stable example id for reporting. |
| `input_data` | yes | Input dictionary used for this example. |
| `expected_output` | yes | Gold label or expected value. |
| `actual_output` | yes | Function output, judge result, or `None` on failure. |
| `metrics` | yes | Numeric metrics such as `{"accuracy": 1.0}`. |
| `execution_time` | yes | Seconds spent evaluating this example. |
| `success` | yes | Whether the evaluator completed this example without an evaluator/runtime failure. |
| `error_message` | no | Failure text, or `None`. |
| `metadata` | no | Method, model, rubric version, parse policy, or other non-secret context. |

The decorator validates `custom_evaluator` signature at decoration time. The required contract is `(func, config, example) -> ExampleResult`. A two-argument evaluator fails with:

```text
ValidationError custom_evaluator must accept (func, config, example), got 2 required parameters: ['func', 'config']
```

## The interview when nothing exists

If no evaluator exists, ask:

1. Which metric did `traigent-eval-choose-metric` select?
2. Can it be checked deterministically from `output`, `expected`, and `input_data`?
3. Does the evaluator need to call the function itself, repeat calls, inspect tool traces, or count judge cost?
4. Is judge output parseable into a strict schema?
5. What should happen on parse failure, tool failure, timeout, or missing labels?

Map the answer to `deterministic`, `llm_based`, `statistical`, or `hybrid`, then pick the lowest tier in the ladder.

## Templates by evaluation method

Use compact patterns inline and the full versions in `references/evaluator-templates.md`.

| Method | Inline pattern |
|---|---|
| `deterministic` | Exact/normalized/schema checks with `scoring_function` or `metric_functions`; fail invalid schema to `0.0`. |
| `llm_based` | Custom evaluator calls a judge with a rubric, parses strict JSON, counts judge cost, and returns `0.0` on parse failure. |
| `statistical` | Custom evaluator repeats the same example, scores agreement or pass rate across reps, and reports variance metadata. |
| `hybrid` | Deterministic gate first; call the judge only if the output passes the gate. |

## Known pitfall: tuple returns and custom scorers

If the optimized function returns `(output, metrics)`, make sure the custom scorer receives the model output, not the whole tuple, unless your scorer intentionally handles tuples. Prefer one of these patterns:

- Keep the production function returning the plain output, and collect extra metrics inside `custom_evaluator`.
- If returning `(output, metrics)`, unwrap before string comparison, JSON parsing, or label matching.
- Do not reuse a metric name for both tuple-returned metrics and evaluator-computed metrics.

## Claim scope

- Deterministic scores measure only the rules encoded in the evaluator.
- Judge scores are model opinions under the stated rubric. Label them as judge scores.
- Statistical scores depend on repeat count, sampling settings, and dataset slice.
- Hybrid scores inherit both the deterministic gate assumptions and judge limitations.

## See Also

- `traigent-eval-choose-metric` - choose objectives before building evaluator code
- `traigent` Step 3.5 - lightweight evaluator sanity gate (run this before the first paid optimization)
- `traigent-eval-audit` - evaluator reliability: manual gold-slice protocol + service-side evaluator-audit action (ACET from optimizer tensor, no new gold collection required)
- `traigent-setup-decorator` - decorator wiring for evaluation options
- `traigent-analyze-results` - inspect the metrics emitted by evaluator runs
- `traigent-dataset-curate` - create and improve the evaluation dataset

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
