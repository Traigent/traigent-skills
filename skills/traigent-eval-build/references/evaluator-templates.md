# Evaluator Templates

These templates are meant to be copied and adapted after the metric has been chosen. Keep any paid judge or provider call behind user approval, `TRAIGENT_RUN_COST_LIMIT`, and a small mock/offline smoke test.

## Deterministic exact, normalized, and schema check

Use this when the expected output is checkable without an LLM judge.

```python
import json
import re

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions

def extract_fields(text: str, required_fields: list[str], *, temperature: float = 0.0) -> str:
    prompt = (
        "Extract the requested fields as a JSON object.\n"
        f"Fields: {', '.join(required_fields)}\n"
        f"Text:\n{text}"
    )
    response = litellm.completion(
        model="gpt-4o-mini",
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())

def exact_normalized_metric(output, expected, input_data) -> float:
    # A JSON gold (dict/list) is compared as parsed JSON: str(expected) would be
    # Python's single-quoted repr and never equal the model's JSON text.
    if isinstance(expected, (dict, list)):
        try:
            return 1.0 if json.loads(output) == expected else 0.0
        except (json.JSONDecodeError, TypeError):
            return 0.0
    return 1.0 if normalize_text(output) == normalize_text(expected) else 0.0

def valid_schema_metric(output, expected, input_data) -> float:
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return 0.0
    # Valid JSON that is not an object (42, null, a list of field names) is a wrong answer.
    if not isinstance(data, dict):
        return 0.0
    required_fields = set(input_data.get("required_fields", []))
    return 1.0 if required_fields.issubset(data) else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/extraction.jsonl",
        metric_functions={
            "exact_normalized": exact_normalized_metric,
            "valid_schema": valid_schema_metric,
        },
    ),
    objectives=["exact_normalized", "valid_schema"],
    configuration_space={"temperature": [0.0, 0.2]},
)
def extract(text: str, required_fields: list[str]) -> str:
    cfg = traigent.get_config()
    return extract_fields(text, required_fields, temperature=cfg["temperature"])
```

## LLM judge with rubric, strict parse, and cost guardrails

Use this only when deterministic labels are insufficient. The judge score is a model opinion under the rubric. Parse failures fail closed to `0.0`, and judge cost is counted in metrics.

Two things the template does on purpose:

- **`judge_cost` is declared `minimize`.** A plain `objectives=[...]` list orients names the SDK does not recognize (such as `judge_cost`) as `maximize`, which would rank the configurations that spend more on the judge higher. Declare every custom objective's orientation with `ObjectiveSchema`.
- **Only the agent call is metered.** The SDK's `cost` and `TRAIGENT_RUN_COST_LIMIT` see the first LLM call per row, not the judge call; see "Cost metering caveat for multi-call evaluators" below.
- **The judge budget is one run-level cap.** `JUDGE_BUDGET` counts every judge call across all rows and trials and refuses the call once the next one would pass the cap; refused rows fail closed with `judge_budget_exhausted`. Spend limits are not tuned variables, so they stay out of `configuration_space`.

```python
import json
import threading
import time
from typing import Any

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.api.types import ExampleResult
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

JUDGE_MODEL = "judge-model-name"
JUDGE_COST_PER_CALL_USD = 0.002

class JudgeBudget:
    """Run-level judge spend cap: refuses a call instead of overspending."""

    def __init__(self, cap_usd: float, per_call_usd: float) -> None:
        self.cap, self.per_call, self.spent = cap_usd, per_call_usd, 0.0
        self._lock = threading.Lock()  # custom evaluators may run in worker threads

    def try_spend(self) -> bool:
        with self._lock:
            if self.spent + self.per_call > self.cap + 1e-12:
                return False
            self.spent += self.per_call
            return True

JUDGE_BUDGET = JudgeBudget(cap_usd=1.00, per_call_usd=JUDGE_COST_PER_CALL_USD)

def prompt_model(prompt: str, *, temperature: float = 0.0) -> str:
    response = litellm.completion(
        model="gpt-4o-mini",
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

def build_judge_prompt(output: Any, expected: Any, input_data: dict[str, Any]) -> str:
    return json.dumps(
        {
            "rubric": (
                "Return JSON only with keys score and reason. "
                "score must be a number from 0 to 1. "
                "Grade factual correctness and completeness against expected."
            ),
            "input": input_data,
            "expected": expected,
            "output": output,
        },
        ensure_ascii=True,
    )

def parse_judge_response(raw: str) -> tuple[float, str, bool]:
    try:
        data = json.loads(raw)
        score = float(data["score"])
        reason = str(data.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0.0, "judge_parse_failure", False
    if not 0.0 <= score <= 1.0:
        return 0.0, "judge_score_out_of_range", False
    return score, reason, True

def llm_judge_evaluator(func, config, example) -> ExampleResult:
    started = time.perf_counter()

    if not JUDGE_BUDGET.try_spend():
        return ExampleResult(
            example_id=str(example.metadata.get("id", "unknown")),
            input_data=example.input_data,
            expected_output=example.expected_output,
            actual_output=None,
            metrics={"quality": 0.0, "judge_cost": 0.0},
            execution_time=time.perf_counter() - started,
            success=False,
            error_message="judge_budget_exhausted",
            metadata={"method": "llm_judge", "parse_policy": "fail_closed"},
        )

    prediction = func(**example.input_data)
    prompt = build_judge_prompt(prediction, example.expected_output, example.input_data)
    judge_response = litellm.completion(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = judge_response.choices[0].message.content or ""
    score, reason, parsed = parse_judge_response(raw)

    return ExampleResult(
        example_id=str(example.metadata.get("id", "unknown")),
        input_data=example.input_data,
        expected_output=example.expected_output,
        actual_output=prediction,
        metrics={"quality": score, "judge_cost": JUDGE_COST_PER_CALL_USD},
        execution_time=time.perf_counter() - started,
        success=parsed,
        error_message=None if parsed else reason,
        metadata={
            "method": "llm_judge",
            "judge_model": JUDGE_MODEL,
            "judge_reason": reason,
            "parse_policy": "fail_closed",
        },
    )

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/qa.jsonl",
        custom_evaluator=llm_judge_evaluator,
    ),
    objectives=ObjectiveSchema.from_objectives([
        ObjectiveDefinition(name="quality", orientation="maximize", weight=1.0),
        ObjectiveDefinition(name="judge_cost", orientation="minimize", weight=0.2),
    ]),
    configuration_space={"temperature": [0.0, 0.3]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(question, temperature=cfg["temperature"])
```

## Cost metering caveat for multi-call evaluators

> **Cost metering caveat (traigent <= 0.27.0):** inside a `custom_evaluator`, the SDK meters only the **first**
> LLM call per row. A template that calls the agent N times, or calls the agent and then a judge, reports
> about 1/N of its real cost in `cost`, and `TRAIGENT_RUN_COST_LIMIT` is enforced against that figure. Budget
> `calls_per_row × rows × trials × price` yourself, keep the limit conservative, and do not read the
> `cost` objective as comparing different repetition counts.
<!-- contract: literal "response = captured_responses[0]" in traigent.core.evaluator_wrapper -->

This applies to the statistical template below (`EVAL_REPS` agent calls per row) and to the LLM-judge and hybrid templates (one agent call plus one judge call per row).

## Statistical agreement over repeated calls

Use this when the same configuration can produce different outputs and stability matters.

The repetition count is part of the measuring instrument, not a knob: agreement (the modal share of `n` samples) is biased upward at small `n`, so trials measured with different counts are not comparable and fewer repetitions look more stable. Keep `EVAL_REPS` fixed for the whole run and out of `configuration_space`. The `accuracy` objective is per-sample correctness, which is what one production call achieves; `agreement` and `majority_accuracy` are diagnostics: they are not objectives, so they do not appear in `trial.metrics`; read them per row from `trial.metadata["example_results"]`. If production really does N-sample majority voting, then majority accuracy is the right objective and `EVAL_REPS` must be that production N.

```python
import time
from collections import Counter

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.api.types import ExampleResult

def prompt_model(prompt: str, *, temperature: float = 0.0) -> str:
    response = litellm.completion(
        model="gpt-4o-mini",
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

EVAL_REPS = 5  # fixed for the whole run; never a tuned variable

def statistical_agreement_evaluator(func, config, example) -> ExampleResult:
    started = time.perf_counter()
    outputs = [func(**example.input_data) for _ in range(EVAL_REPS)]
    # SDK builtin accuracy is case-insensitive + whitespace-trimmed (since SDK #1473)
    normalized = [str(output).strip().lower() for output in outputs]
    expected = str(example.expected_output).strip().lower()
    counts = Counter(normalized)
    most_common, count = counts.most_common(1)[0]

    return ExampleResult(
        example_id=str(example.metadata.get("id", "unknown")),
        input_data=example.input_data,
        expected_output=example.expected_output,
        actual_output=most_common,
        metrics={
            "accuracy": sum(o == expected for o in normalized) / EVAL_REPS,  # what one production call achieves
            "agreement": count / EVAL_REPS,  # diagnostic, same n for every trial
            "majority_accuracy": 1.0 if most_common == expected else 0.0,  # diagnostic
        },
        execution_time=time.perf_counter() - started,
        success=True,
        metadata={
            "method": "statistical_agreement",
            "reps": EVAL_REPS,
            "unique_outputs": len(counts),
        },
    )

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/qa.jsonl",
        custom_evaluator=statistical_agreement_evaluator,
    ),
    objectives=["accuracy", "cost"],
    configuration_space={"temperature": [0.2, 0.7]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(question, temperature=cfg["temperature"])
```

## Hybrid deterministic gate then judge

Use this when invalid outputs should fail before spending judge calls. Rows that pass the gate make two LLM calls (agent, then judge) and only the first is metered; see "Cost metering caveat for multi-call evaluators" above.

```python
import json
import time

import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.api.types import ExampleResult
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

JUDGE_MODEL = "judge-model-name"

def extract_json(text: str, *, temperature: float = 0.0) -> str:
    response = litellm.completion(
        model="gpt-4o-mini",
        temperature=temperature,
        messages=[
            {
                "role": "user",
                "content": f"Extract the relevant fields as a JSON object only:\n{text}",
            }
        ],
    )
    return response.choices[0].message.content or ""

def parse_json_object(value: str) -> tuple[dict, str | None]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        return {}, f"invalid_json: {exc}"
    if not isinstance(data, dict):
        return {}, "not_a_json_object"
    return data, None

def judge_json_quality(output: dict, expected: dict, input_data: dict) -> tuple[float, str, bool]:
    prompt = json.dumps(
        {
            "rubric": "Return JSON only: {\"score\": number, \"reason\": string}.",
            "input": input_data,
            "expected": expected,
            "prediction": output,
        },
        ensure_ascii=True,
    )
    judge_response = litellm.completion(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = judge_response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
        score = float(parsed["score"])
        reason = str(parsed.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0.0, "judge_parse_failure", False
    if not 0.0 <= score <= 1.0:
        return 0.0, "judge_score_out_of_range", False
    return score, reason, True

def hybrid_evaluator(func, config, example) -> ExampleResult:
    started = time.perf_counter()
    prediction = func(**example.input_data)
    data, gate_error = parse_json_object(prediction)

    if gate_error is not None:
        return ExampleResult(
            example_id=str(example.metadata.get("id", "unknown")),
            input_data=example.input_data,
            expected_output=example.expected_output,
            actual_output=prediction,
            metrics={"valid_json": 0.0, "quality": 0.0, "judge_cost": 0.0},
            execution_time=time.perf_counter() - started,
            success=False,
            error_message=gate_error,
            metadata={"method": "hybrid_gate_then_judge", "judge_called": False},
        )

    score, reason, parsed = judge_json_quality(data, example.expected_output, example.input_data)
    judge_cost = 0.002
    return ExampleResult(
        example_id=str(example.metadata.get("id", "unknown")),
        input_data=example.input_data,
        expected_output=example.expected_output,
        actual_output=data,
        metrics={"valid_json": 1.0, "quality": score, "judge_cost": judge_cost},
        execution_time=time.perf_counter() - started,
        success=parsed,
        error_message=None if parsed else reason,
        metadata={
            "method": "hybrid_gate_then_judge",
            "judge_called": True,
            "parse_policy": "fail_closed",
            "judge_reason": reason,
        },
    )

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/extraction.jsonl",
        custom_evaluator=hybrid_evaluator,
    ),
    objectives=ObjectiveSchema.from_objectives([
        ObjectiveDefinition(name="valid_json", orientation="maximize", weight=1.0),
        ObjectiveDefinition(name="quality", orientation="maximize", weight=1.0),
        ObjectiveDefinition(name="judge_cost", orientation="minimize", weight=0.2),
    ]),
    configuration_space={"temperature": [0.0, 0.2]},
)
def extract(text: str) -> str:
    cfg = traigent.get_config()
    return extract_json(text, temperature=cfg["temperature"])
```
