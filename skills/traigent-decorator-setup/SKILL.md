---
name: traigent-decorator-setup
description: "Configure the @traigent.optimize() decorator with evaluation, injection, and execution options. Use when setting up eval_dataset, choosing injection_mode, choosing the optimization algorithm or offline execution, defining objectives, naming/labeling a run with experiment_name (there is no tags/metadata argument), using EvaluationOptions/InjectionOptions/ExecutionOptions, or integrating custom evaluators. Provide the agent function + its path, an eval dataset, and the objective(s)."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.3"
---

# Traigent Decorator Setup

## When to Use

Use this skill when you need to go beyond the basic `@traigent.optimize()` decorator and configure:

- Evaluation datasets, custom evaluators, scoring functions, or metric functions
- Injection modes (how optimized configs reach your function)
- Execution behavior (`algorithm` and `offline` — where and how optimization runs)
- Multi-objective optimization with weighted objectives
- Naming/labeling a run with `experiment_name` (there is no `tags`/`metadata` argument)
- Portal-synced or zero-egress local execution

## Inputs to Provide (Quick Cycle)

To wire and run an optimization, three inputs are needed — supply them up front (e.g. when invoking the skill: agent name, agent path, dataset path) so setup proceeds without back-and-forth:

1. **Agent function** — the function to optimize, plus the **file/module path** where it lives, so `@traigent.optimize()` can be applied to it.
2. **Evaluation dataset** — a path to a JSONL eval set (one `input`/`output` per line) used to score each trial.
3. **Objective(s)** — what to optimize: a string list (e.g. `["accuracy"]`) or a weighted `ObjectiveSchema` (see [Objectives](#objectives) below).

A typical **quick cycle is two steps**: configure the decorator with this skill, then launch with the **`traigent-run-optimization`** skill. The decorator config below is identical whether you pass these inputs at invocation or provide them interactively — if any is missing, ask for it before wiring the decorator.

**Multiple candidate agents?** If the skill is invoked without an agent and the project has more than one function that could be optimized (e.g. several that call an LLM), do **not** guess — list the candidates and ask the user which one to wire. Optimize one decorated function per run.

## Imports

```python
import litellm
import traigent
from traigent.api.decorators import (
    EvaluationOptions,
    InjectionOptions,
    ExecutionOptions,
)

def prompt_model(prompt: str, *, model: str = "gpt-4o-mini", temperature: float = 0.0, max_tokens: int = 512) -> str:
    response = litellm.completion(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
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
    return prompt_model(query, model=cfg["model"])
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
    return prompt_model(query, model=cfg["model"])
```

## Naming and Labeling Runs

Use `experiment_name` to label a run so you can identify it in the Traigent portal and in local
storage. It is the **only** labeling mechanism on the decorator — the current SDK has **no
`tags` or `metadata` argument** on `@traigent.optimize()` or on the runtime `.optimize()` /
`.optimize_sync()` methods. Do not try to attach tags; encode whatever you need (agent name,
variant, dataset version) into a descriptive `experiment_name` instead.

```python
@traigent.optimize(
    experiment_name="txt2sql v3 (claude, ACL>=0.8)",  # shown in the portal; the only label knob
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(query, model=cfg["model"])
```

- `experiment_name` accepts spaces and punctuation (it is not a Python identifier).
- When omitted, the decorated function's `__name__` is used; the `TRAIGENT_EXPERIMENT_NAME`
  environment variable is used as a fallback if no explicit value is passed.
- The label is set on the **decorator**, not on the run call — there is no `experiment_name`
  (or `tags`) parameter on `.optimize()` / `.optimize_sync()`.

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
    return prompt_model(question, temperature=cfg["temperature"])
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
    return prompt_model(f"Summarize: {text}", model=cfg["model"])
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
    return prompt_model(query, model=cfg["model"])
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
    return prompt_model(query, model=config["model"])
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

Where and how runs execute is controlled by two public knobs: `algorithm` and `offline`.
See `references/execution-modes.md` for the full reference.

```python
@traigent.optimize(
    algorithm="auto",   # default: Traigent cloud smart optimizer
    offline=False,      # set True for a fully-local, zero-egress run
    execution=ExecutionOptions(local_storage_path="./results"),
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(query, model=cfg["model"])
```

### `algorithm` and `offline`

| Choice | Behavior |
|---|---|
| `algorithm="auto"` (default) | Traigent cloud smart optimizer proposes trials; your agent/LLM calls run in your environment. Results sync to the portal. |
| `algorithm="grid"` / `"random"` | Local search in the SDK. Results still sync to the portal unless `offline=True`. |
| `algorithm="bayesian"`/`"tpe"`/`"optuna*"`/… | Smart optimizers are **cloud-only**; use them only with a Traigent cloud connection. |
| `offline=True` | Fully local, **zero backend egress**. Results are not synced to the portal. |

The synced path sends configuration IDs and numeric metrics for portal result history, not
example inputs/outputs/prompts. Use `offline=True` only when zero outbound traffic is required.
To optimize an external HTTP/MCP service, put the service call in your decorated function or
custom evaluator; keep optimization strategy on the same `algorithm`/`offline` knobs.

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
    return prompt_model(query, model=cfg["model"])

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
    return prompt_model(
        question,
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
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
- `traigent-quickstart` - Installation, API-key setup, and first cloud-smart optimization

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

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
