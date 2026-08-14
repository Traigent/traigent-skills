# EvaluationOptions Reference

`EvaluationOptions` is a Pydantic model that groups all evaluation-related settings for the `@traigent.optimize()` decorator.

```python
from traigent.api.decorators import EvaluationOptions
```

## Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `eval_dataset` | `str \| list[str] \| Dataset \| None` | `None` | Path to a JSONL evaluation dataset, a list of dataset paths, or a `Dataset` object. Each row should contain input fields and an expected output. |
| `custom_evaluator` | `Callable \| None` | `None` | A callable with signature `(func, config, example) -> ExampleResult`. Gives full control over how each example is executed and scored. |
| `scoring_function` | `Callable \| None` | `None` | A lightweight callable with signature `(output, expected) -> float`. Returns a numeric score for each example. |
| `metric_functions` | `dict[str, Callable] \| None` | `None` | Dictionary mapping metric names to callables. Each callable has signature `(output, expected, input_data) -> float`. |

## Custom Evaluator

The `custom_evaluator` gives you full control over trial execution and measurement. It receives the function, the trial config, and each dataset example.

### Signature

```python
def custom_evaluator(
    func: Callable,
    config: dict[str, Any],
    example: dict[str, Any],
) -> ExampleResult:
    ...
```

### Parameters

- `func` - The original decorated function (not wrapped).
- `config` - The configuration being tested in this trial (e.g., `{"model": "gpt-4o", "temperature": 0.5}`).
- `example` - An `EvaluationExample` with `input_data`, `expected_output`, and optional `metadata`.

### Return Value

Must return an `ExampleResult` containing the example inputs, expected output, actual output, metrics, execution time, and success state.

### Example

```python
import litellm
from traigent.evaluators.base import ExampleResult

def prompt_model(prompt: str, *, model: str = "gpt-4o-mini", temperature: float = 0.0) -> str:
    response = litellm.completion(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

def my_evaluator(func, config, example):
    import time
    start = time.time()
    prediction = func(example.input_data["question"])
    latency = time.time() - start

    score = 1.0 if example.expected_output in prediction else 0.0

    return ExampleResult(
        example_id=str(example.metadata.get("id", "example")),
        input_data=example.input_data,
        expected_output=example.expected_output,
        actual_output=prediction,
        metrics={"score": score, "latency": latency * 1000},  # bare `latency` key; ms on SDKs after 0.22.0 (see version-matrix: latency-unit)
        execution_time=latency,
        success=True,
    )

@traigent.optimize(
    evaluation=EvaluationOptions(custom_evaluator=my_evaluator),
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(question, model=cfg["model"])
```

Objectives bind to metric keys by exact name: an `objectives=["latency"]` entry
reads the bare `latency` key (in milliseconds on SDKs after 0.22.0 —
see version-matrix: `latency-unit`), **not** a suffixed name like `latency_ms`. Emit the exact
key your objectives reference, or that objective silently has no metric.
`execution_time` is a separate first-class field, always in seconds — it is not a
metric key.

### Validation

Traigent validates the `custom_evaluator` signature at decoration time. If your callable has parameters named `output`, `expected`, and `input_data`, Traigent will raise a `ValidationError` suggesting you use `metric_functions` instead. This catches a common mistake where a metric evaluator is passed as a custom evaluator.

## Scoring Function

A simpler alternative to `custom_evaluator`. Traigent handles function execution and passes the output and expected value to your scorer.

### Signature

```python
def scoring_function(output: str, expected: str) -> float:
    ...
```

### Example

```python
def fuzzy_match(output: str, expected: str) -> float:
    pred = output.strip().lower()
    exp = expected.strip().lower()
    if pred == exp:
        return 1.0
    if exp in pred:
        return 0.8
    return 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="test_data.jsonl",
        scoring_function=fuzzy_match,
    ),
    objectives=["accuracy"],
    configuration_space={"temperature": [0.0, 0.5, 1.0]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(query, temperature=cfg["temperature"])
```

## Metric Functions

Use `metric_functions` when you want to track multiple named metrics per example. Each metric function receives the prediction, expected output, and input data.

### Signature

```python
def metric_fn(output: Any, expected: Any, input_data: dict) -> float:
    ...
```

### Example

```python
def accuracy(output, expected, input_data) -> float:
    # SDK builtin accuracy is case-insensitive + whitespace-trimmed (matches SDK since #1473)
    return 1.0 if output.strip().lower() == expected.strip().lower() else 0.0

def conciseness(output, expected, input_data) -> float:
    return max(0.0, 1.0 - len(output) / 2000)

def relevance(output, expected, input_data) -> float:
    keywords = input_data.get("keywords", [])
    if not keywords:
        return 1.0
    found = sum(1 for kw in keywords if kw.lower() in output.lower())
    return found / len(keywords)

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval_set.jsonl",
        metric_functions={
            "accuracy": accuracy,
            "conciseness": conciseness,
            "relevance": relevance,
        },
    ),
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def summarize(text: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(f"Summarize: {text}", model=cfg["model"])
```

## Choosing Between Evaluation Approaches

| Scenario | Recommended Approach |
|---|---|
| Standard accuracy on a JSONL dataset | `eval_dataset` alone (uses built-in evaluation) |
| Simple right/wrong scoring | `scoring_function` |
| Multiple metrics (accuracy + latency + cost) | `metric_functions` |
| Custom execution logic (retries, pre/post processing) | `custom_evaluator` |
| LLM-as-judge evaluation | `custom_evaluator` (call judge LLM inside evaluator) |

## Dataset Format

The `eval_dataset` JSONL file should have one JSON object per line. At minimum, include input fields that match your function parameters and an `expected` field:

```json
{"question": "What is Python?", "expected": "A programming language"}
{"question": "What is 2+2?", "expected": "4"}
```

Multiple datasets can be provided as a list:

```python
EvaluationOptions(eval_dataset=["train.jsonl", "validation.jsonl"])
```
