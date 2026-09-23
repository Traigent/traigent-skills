# DSPy Adapter Reference

> **Dry-run first.** Before running any real DSPy optimization, activate `enable_mock_mode_for_quickstart()`, run, review the cost estimate, and get explicit approval. See the `traigent-boost-agent` skill for the dry-run-first / cost-approval mandate.
> - Mock mode's canned text cannot satisfy DSPy's structured outputs (every trial
>   fails). Dry-run with `dspy.utils.DummyLM([...])` as the LM instead of `dspy.LM(...)` — one dict per
>   call, keyed by the signature's output fields, e.g. `DummyLM([{"answer": "4"}] * 50)`.

## Overview

Traigent provides the `DSPyPromptOptimizer` adapter for integrating DSPy's automatic prompt optimization into your workflow. DSPy optimizes prompts through demonstration selection and instruction tuning, while Traigent handles model selection and parameter tuning.

## Installation

```bash
pip install "traigent>=0.19" "dspy==3.3.1"  # the version these examples were verified on
```

## DSPyPromptOptimizer

The adapter wraps DSPy's MIPROv2 and BootstrapFewShot optimizers.

> **Use `method="bootstrap"` on released SDKs.** `method="mipro"` (the constructor default) raises
> `TypeError: MIPROv2.__init__() got an unexpected keyword argument 'requires_permission_to_run'`
> on `traigent<=0.27.0` with DSPy 2.6/3.x. Pass `method="bootstrap"` explicitly until a fixed SDK
> release.

### Import

```python
from traigent.integrations.dspy_adapter import DSPyPromptOptimizer
```

### Constructor

```python
optimizer = DSPyPromptOptimizer(
    method="bootstrap",       # "mipro" (the default; see the note above) or "bootstrap"
    teacher_model=None,       # keyword-only: optional teacher model id
    auto_setting="medium",    # keyword-only: MIPRO budget, "light" | "medium" | "heavy"
)
```

The constructor takes no other arguments; anything else raises `TypeError`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `method` | `"mipro" \| "bootstrap"` | `"mipro"` | Which DSPy optimizer to use. `"mipro"` uses MIPROv2 (instruction + demo optimization). `"bootstrap"` uses BootstrapFewShot (demo-only optimization). |
| `teacher_model` | `str \| None` | `None` | Keyword-only. Model name for the teacher (e.g., `"gpt-4o"`). If `None`, uses the same model as the student. |
| `auto_setting` | `"light" \| "medium" \| "heavy"` | `"medium"` | Keyword-only. MIPROv2's `auto` budget; ignored by `"bootstrap"`. |

### optimize_prompt()

```python
result = optimizer.optimize_prompt(
    module=my_dspy_module,       # DSPy module to optimize
    trainset=train_examples,     # List of dspy.Example objects
    metric=accuracy_fn,          # Metric function: (example, prediction, trace=None) -> float | bool
    max_bootstrapped_demos=4,    # keyword-only tuning knobs, shown with their defaults
    max_labeled_demos=16,
    num_candidates=10,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `module` | `Any` | (required) | The DSPy module to optimize. |
| `trainset` | `list[Any]` | (required) | Training examples (`dspy.Example` objects). |
| `metric` | `Callable[[Any, Any], float]` | (required) | Scores a prediction against an example. |
| `max_bootstrapped_demos` | `int` | `4` | Keyword-only. Most bootstrapped demonstrations to keep. |
| `max_labeled_demos` | `int` | `16` | Keyword-only. Most labeled demonstrations to keep. |
| `num_candidates` | `int` | `10` | Keyword-only. MIPROv2 instruction candidates; ignored by `"bootstrap"`. |
| `requires_permission_to_run` | `bool` | `False` | Keyword-only. MIPROv2 confirmation prompt; ignored by `"bootstrap"`. |

Returns a `PromptOptimizationResult`:

| Field | Type | Description |
|---|---|---|
| `optimized_module` | `Any` | The optimized DSPy module with tuned prompts and demonstrations. |
| `method` | `str` | The optimization method used (`"mipro"` or `"bootstrap"`). |
| `num_demos` | `int` | Number of demonstrations in the optimized prompt. |
| `trainset_size` | `int` | Size of the training set used. |
| `best_score` | `float \| None` | Best metric score achieved during optimization. |
| `metadata` | `dict[str, Any]` | Additional metadata from the optimization process. |

## BootstrapFewShot Method

BootstrapFewShot selects the best few-shot demonstrations from the training set:

```python
import dspy
from traigent.integrations.dspy_adapter import DSPyPromptOptimizer

# Configure DSPy
lm = dspy.LM("gpt-4o-mini")
dspy.configure(lm=lm)

# Define a DSPy module
class QAModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict("question -> answer")

    def forward(self, question):
        return self.predict(question=question)

# Define metric (SDK builtin accuracy is case-insensitive + whitespace-trimmed since SDK #1473)
def exact_match(example, prediction, trace=None):
    return example.answer.strip().lower() == prediction.answer.strip().lower()

# Prepare training data
trainset = [
    dspy.Example(question="What is 2+2?", answer="4").with_inputs("question"),
    dspy.Example(question="Capital of France?", answer="Paris").with_inputs("question"),
    # ... more examples
]

optimizer = DSPyPromptOptimizer(method="bootstrap")
result = optimizer.optimize_prompt(
    module=QAModule(),
    trainset=trainset,
    metric=exact_match,
)

print(f"Best score: {result.best_score}")
print(f"Selected {result.num_demos} demonstrations")

# Use the optimized module
optimized_qa = result.optimized_module
answer = optimized_qa(question="What is the speed of light?")
```

## MIPRO Method

MIPROv2 optimizes both the instruction text and the few-shot demonstrations. It is selected with
`method="mipro"` (plus `teacher_model=` and `auto_setting=` if needed), but on `traigent<=0.27.0`
it fails with the `TypeError` in the note above with DSPy 2.6/3.x (checked on 2.6.27 and 3.3.1).
Until a fixed SDK release, use `method="bootstrap"`.

## Combining DSPy with Traigent Model Optimization

Use Traigent for model/parameter optimization and DSPy for prompt optimization:

```python
import traigent
import dspy

@traigent.optimize(
    eval_dataset="qa_eval.jsonl",
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o", "claude-3-haiku-20240307"],
        "temperature": [0.0, 0.3, 0.7],
    },
    objectives=["accuracy"],
    max_trials=9,
)
def optimized_qa(question):
    config = traigent.get_config()

    # Traigent manages model selection
    lm = dspy.LM(config["model"], temperature=config["temperature"])

    # DSPy handles the prompt structure. dspy.context, not dspy.configure: trials run on
    # worker threads, and dspy.configure fails on every thread but the first.
    with dspy.context(lm=lm):
        qa = dspy.Predict("question -> answer")
        result = qa(question=question)
    return result.answer

# Traigent finds the best model + temperature
results = optimized_qa.optimize_sync()
```

For a two-stage approach (Traigent model optimization, then DSPy prompt optimization):

```python
# Stage 1: Find the best model with Traigent
model_results = optimized_qa.optimize_sync()
best_model = model_results.best_config["model"]
best_temp = model_results.best_config["temperature"]

# Stage 2: Optimize prompts with DSPy using the best model
lm = dspy.LM(best_model, temperature=best_temp)
dspy.configure(lm=lm)

optimizer = DSPyPromptOptimizer(method="bootstrap")  # "mipro" fails on traigent<=0.27.0
prompt_result = optimizer.optimize_prompt(
    module=QAModule(),
    trainset=trainset,
    metric=exact_match,
)

# Use the fully optimized system
final_module = prompt_result.optimized_module
```

## Tips

- MIPRO is more powerful but slower; BootstrapFewShot is faster for demo-only optimization (and is the method that runs on `traigent<=0.27.0`)
- Use a stronger teacher model (e.g., `gpt-4o`) when the student model is smaller
- DSPy requires structured inputs/outputs; define your module's signature clearly
- Training set quality matters more than quantity for few-shot optimization
- The `optimized_module` retains all DSPy functionality and can be saved/loaded with `dspy.save`/`dspy.load`
