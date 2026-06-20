---
name: traigent-decorator-setup
description: "Configure the @traigent.optimize() decorator with evaluation, injection, and execution options. Use when setting up eval_dataset, choosing injection_mode, choosing the optimization algorithm or offline execution, defining objectives, using EvaluationOptions/InjectionOptions/ExecutionOptions, or integrating custom evaluators."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.1"
---

# Traigent Decorator Setup

## When to Use

Use this skill when you need to go beyond the basic `@traigent.optimize()` decorator and configure:

- Evaluation datasets, custom evaluators, scoring functions, or metric functions
- Injection modes (how optimized configs reach your function)
- Execution behavior (`algorithm` and `offline` — where and how optimization runs)
- Multi-objective optimization with weighted objectives
- Privacy-preserving or local-only execution

## Imports

```python
import traigent
from traigent.api.decorators import (
    EvaluationOptions,
    InjectionOptions,
    ExecutionOptions,
)
```

## Objectives

Objectives tell Traigent what to optimize for. Pass them as a string list or as an `ObjectiveSchema` for weighted multi-objective optimization.

### String List (Simple)

```python
@traigent.optimize(
    objectives=["accuracy", "cost"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=cfg["model"], prompt=query)
```

### ObjectiveSchema (Weighted)

```python
from traigent.core.objectives import ObjectiveSchema, ObjectiveDefinition

schema = ObjectiveSchema(
    objectives=[
        ObjectiveDefinition(name="accuracy", weight=0.7, orientation="maximize"),
        ObjectiveDefinition(name="cost", weight=0.3, orientation="minimize"),
    ],
    weights_sum=1.0,
    weights_normalized={"accuracy": 0.7, "cost": 0.3},
)

@traigent.optimize(
    objectives=schema,
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=cfg["model"], prompt=query)
```

## Evaluation Setup

Configure how Traigent evaluates each trial using `EvaluationOptions`.

### Fields

| Field | Type | Description |
|---|---|---|
| `eval_dataset` | `str \| list[str] \| Dataset \| None` | Path to JSONL dataset or list of paths |
| `custom_evaluator` | `Callable \| None` | Full-control evaluator: `(func, config, example) -> ExampleResult` |
| `scoring_function` | `Callable \| None` | Lightweight scorer: `(output, expected) -> float` |
| `metric_functions` | `dict[str, Callable] \| None` | Named metrics: `{"accuracy": fn, "relevance": fn}` |

### When to Use Each

| Approach | Best For | Signature |
|---|---|---|
| `eval_dataset` only | Built-in evaluation with default metrics | N/A (path string) |
| `scoring_function` | Simple pass/fail or numeric scoring | `(output, expected) -> float` |
| `metric_functions` | Multiple named metrics per example | `{"name": (output, expected, input_data) -> float}` |
| `custom_evaluator` | Full control over execution and measurement | `(func, config, example) -> ExampleResult` |

### Example: Scoring Function

```python
def exact_match(output: str, expected: str) -> float:
    return 1.0 if output.strip() == expected.strip() else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="qa_pairs.jsonl",
        scoring_function=exact_match,
    ),
    objectives=["accuracy"],
    configuration_space={"temperature": [0.0, 0.3, 0.7]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(temperature=cfg["temperature"], prompt=question)
```

### Example: Metric Functions

```python
def accuracy_metric(output, expected, input_data) -> float:
    return 1.0 if output.strip() == expected.strip() else 0.0

def length_metric(output, expected, input_data) -> float:
    return min(len(output) / 500, 1.0)

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="test_data.jsonl",
        metric_functions={
            "accuracy": accuracy_metric,
            "brevity": length_metric,
        },
    ),
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def summarize(text: str) -> str:
    cfg = traigent.get_config()
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=cfg["model"], prompt=f"Summarize: {text}")
```

## Injection Modes

Injection mode controls how the optimized configuration reaches your function code.

### Context Mode (Default)

The recommended mode. Uses Python `contextvars` for thread-safe config access.

```python
@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()  # Thread-safe context access
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=cfg["model"], prompt=query)
```

### Parameter Mode

Passes config as an explicit function parameter. Set `config_param` to the parameter name.

```python
@traigent.optimize(
    injection=InjectionOptions(
        injection_mode="parameter",
        config_param="config",
    ),
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str, config: dict = None) -> str:
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=config["model"], prompt=query)
```

### Seamless Mode

Zero code change. Traigent uses AST transformation to inject parameters into LLM calls automatically.

```python
@traigent.optimize(
    injection=InjectionOptions(injection_mode="seamless"),
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.1, 0.5, 0.9],
    },
)
def my_func(query: str) -> str:
    # No get_config() call needed - Traigent transforms AST automatically
    return openai.chat.completions.create(
        model="gpt-4o-mini",  # Will be overridden by Traigent
        messages=[{"role": "user", "content": query}],
    )
```

## Execution Options

Where and how runs execute is controlled by two knobs — `algorithm` and `offline` — not an
`execution_mode` selector (that was removed). See `references/execution-modes.md` for the full
reference.

```python
@traigent.optimize(
    algorithm="auto",   # default: cloud-first, auto-falls-back to local if the backend is unreachable
    offline=False,      # set True for a fully-local, zero-egress run
    execution=ExecutionOptions(local_storage_path="./results"),
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=cfg["model"], prompt=query)
```

### `algorithm` and `offline`

| Choice | Behavior |
|---|---|
| `algorithm="auto"` (default) | Cloud optimizer proposes trials; your agent/LLM run locally. Degrades to a local search (with a warning) if the backend is unreachable. |
| `algorithm="grid"` / `"random"` | Runs entirely locally — no backend round-trip. |
| `algorithm="bayesian"`/`"tpe"`/`"optuna*"`/… | Smart optimizers — **cloud-only**; raise if the cloud is unavailable. |
| `offline=True` | Fully local, **zero backend egress** (also `TRAIGENT_OFFLINE=1`). |

The cloud path sends only configuration IDs and numeric metrics — never your example
inputs/outputs/prompts. "Privacy-preserving" is the default; for *no network at all* use
`offline=True`. To optimize an external HTTP/MCP service, pass
`evaluator=ExternalServiceEvaluator(hybrid_api=HybridAPIOptions(endpoint=...))`. The legacy
`execution_mode`, `privacy_enabled`, and `cloud_fallback_policy` params are deprecated no-ops.

## Config Access Lifecycle

| When | API | Notes |
|---|---|---|
| During optimization trials | `traigent.get_config()` | Returns current trial config. Thread-safe via contextvars. |
| During optimization trials (strict) | `traigent.get_trial_config()` | Raises `OptimizationStateError` if not in active trial. |
| After `apply_best_config()` | `traigent.get_config()` | Returns the applied best config. |
| From optimization results | `results.best_config` | Dict with the best configuration found. |
| From the function object | `func.current_config` | Current config on the `OptimizedFunction` instance. |

### Lifecycle Example

```python
@traigent.optimize(
    eval_dataset="data.jsonl",
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()  # Works during trials AND after apply_best_config
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(model=cfg["model"], prompt=query)

# Run optimization
results = await my_func.optimize(max_trials=6, algorithm="grid")

# Inspect results
print(results.best_config)   # {"model": "gpt-4o"}
print(results.best_score)    # 0.92

# Lock in the best config for production use
my_func.apply_best_config(results)

# Now calling my_func uses the best config automatically
answer = my_func("What is Python?")
```

## Complete Example

Putting together evaluation, injection, and execution options:

```python
import traigent
from traigent.api.decorators import EvaluationOptions, ExecutionOptions

def exact_match(output: str, expected: str) -> float:
    return 1.0 if output.strip() == expected.strip() else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="qa_test.jsonl",
        scoring_function=exact_match,
    ),
    execution=ExecutionOptions(
        local_storage_path="./optimization_results",
    ),
    objectives=["accuracy", "cost"],
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3, 0.7, 1.0],
        "max_tokens": [256, 512, 1024],
    },
)
def answer_question(question: str) -> str:
    cfg = traigent.get_config()
    # call_llm: replace with your actual LLM call, e.g. litellm.completion(...)
    return call_llm(
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        prompt=question,
    )

# Run optimization
results = await answer_question.optimize(max_trials=10, algorithm="bayesian")

# Apply best configuration for production
answer_question.apply_best_config(results)

# Use in production
answer = answer_question("What is the capital of France?")
```

## See Also

- `references/evaluation-options.md` - Full EvaluationOptions field reference
- `references/injection-modes.md` - Detailed injection mode comparison
- `references/execution-modes.md` - Full ExecutionOptions field reference
- `traigent-build-evaluator` - Deep evaluator implementation, ExampleResult, custom evaluators, and evaluator templates
- `traigent-choose-metric` - Metric interview and objective selection before decorator wiring
- `traigent-quickstart` - Installation, API-key setup, and first optimization (prerequisite reading for cloud mode)

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
