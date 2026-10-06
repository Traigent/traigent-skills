# Declaring a task category: `EvaluationOptions.task_type`

Requires `traigent>=0.28.0`. `EvaluationOptions.task_type` is supported since 0.28.0
(see version-matrix: evaluation-task-type).
On older SDKs, including 0.27.x, do not pass `task_type` — `EvaluationOptions` forbids
unknown fields there and construction raises `ValidationError: Extra inputs are not
permitted`. Follow the no-`task_type` path in this skill's `SKILL.md` instead:
Claim Scope, "Precondition — an audit needs an independent anchor".
Check the installed `traigent.__version__` before pointing a user at this recipe.

## Recipe

Keep your existing evaluation settings and add the coarse task category. This example
only constructs the configuration; it does not read the dataset or run an audit:

```python runnable
from traigent.api.decorators import EvaluationOptions

options = EvaluationOptions(eval_dataset="eval.jsonl", task_type="exact_match")
assert options.eval_dataset == "eval.jsonl"
assert options.task_type == "exact_match"
```

## What the category does — and does not do

`task_type` is a coarse task category, not an anchor name. The service maps the category to
an evaluator-quality anchor policy; you never name an anchor yourself, and declaring a
category does not guarantee that an anchor exists for your task. Unknown categories resolve
to "no anchor". Free-form tasks have no anchor by construction. Without an independent
correctness signal registered for the run, the audit abstains — a correct refusal, not a
failure to fix on the client side.
