---
name: traigent-choose-metric
description: "Choose Traigent objectives and metric functions before optimizing. Use when asked which metric to use, how to measure quality, whether to optimize accuracy/cost/latency/safety, how to name objectives, how to combine multiple objectives, when to use custom metric_functions, or how to turn product goals into Traigent objectives."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.1.1"
---

# Traigent Choose Metric

## When to Use

Use this skill before configuring `@traigent.optimize()` when the user has not yet pinned what "good" means.

- Prefer plain `objectives=["accuracy", "cost"]` lists unless the project already needs weighted objective schemas.
- Use built-in metric names when they match the job: `accuracy`, `success_rate`, `error_rate`, `avg_output_length`, `cost`, `latency`.
- Use custom `metric_functions` when the task has checkable domain logic that a built-in metric cannot express.
- If the key property is a must-not-violate safety condition, treat it as a gate or constraint, not as an ordinary objective.

## The metric interview

Ask these six questions and write down the answers before coding:

1. What does "good" mean in product terms: correct answer, better rank, valid JSON, safe refusal, lower cost, lower latency, or higher reliability?
2. Is there checkable ground truth, or does the team need a rubric/judge?
3. Is the unit one input-output example, a multi-turn conversation, or an agent trace with tools?
4. Which failure is unacceptable even if the average score improves?
5. What budget matters: dollars, latency, tokens, calls, tool invocations, or review time?
6. Who consumes the score: optimizer, CI gate, release owner, customer report, or debugging workflow?

Convert the answers into one primary metric, optional secondary objectives, and any hard gates.

## Measure-type grounding

Use this vocabulary in prose and tables. Do not import these names.

| Measure type | What it asks | Common evaluation method |
|---|---|---|
| `sanity_check` | Does the wiring work and return parseable outputs? | deterministic |
| `accuracy` | Does the output match a known label, answer, or test result? | deterministic or statistical |
| `quality` | Is the answer useful, complete, grounded, or well-written? | llm_based or hybrid |
| `latency` | How long does the call or workflow take? | deterministic |
| `safety` | Did the system avoid a prohibited action or output? | deterministic or hybrid |
| `efficiency` | Did the system use fewer tokens, calls, tools, or dollars? | deterministic |
| `reliability` | Does the behavior remain stable across repeats or noisy inputs? | statistical or hybrid |

Evaluation methods:

| Method | Use when |
|---|---|
| `deterministic` | Exact match, normalized match, schema validation, tests, cost, latency, or tool-call rules can be checked directly. |
| `llm_based` | A rubric is required and deterministic labels are insufficient. Label the result as a judge score. LLM-based evaluators are subject to service-side evaluator-quality auditing (ACET) after runs complete — the optimizer tensor is used to retroactively assess the judge, no new gold collection required. Favor a verifiable anchor (execution-match, unit-test pass, MCQ exact match) where the task allows, as it enables honest confidence from the service audit. |
| `statistical` | Repeated runs, variance, agreement, or confidence intervals matter. |
| `hybrid` | A deterministic gate should run before a judge or repeated-sample score. |

## From answers to objectives

Start with built-ins when possible:

```python
import litellm
import traigent

def prompt_model(prompt: str, *, model: str, temperature: float = 0.0) -> str:
    response = litellm.completion(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

@traigent.optimize(
    objectives=["accuracy", "cost"],
    configuration_space={
        "model": ["gpt-4o-mini", "gpt-4o"],
        "temperature": [0.0, 0.3],
    },
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(question, model=cfg["model"], temperature=cfg["temperature"])
```

Use custom metric functions when the domain has a checkable rule. Default to an `accuracy`-labeled primary quality objective when correctness or answer quality applies, either as a built-in objective or as a `metric_functions` key. Name the primary quality metric after the product concept only when `accuracy` semantically does not fit the problem, such as ranking quality, generation quality, schema validity, or latency-only tuning; note why accuracy was skipped, and include that name in `objectives` only if the optimizer should trade off against it.

In the schema-only example below, `valid_schema` is the product-concept KPI because output format validity is the primary target; add an `accuracy` metric too if answer correctness also matters.

```python
import json

import traigent
from traigent.api.decorators import EvaluationOptions

def valid_schema_metric(output, expected, input_data) -> float:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return 0.0
    required = {"invoice_id", "amount_due", "due_date"}
    return 1.0 if required.issubset(data) else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/invoices.jsonl",
        metric_functions={"valid_schema": valid_schema_metric},
    ),
    objectives=["valid_schema", "cost"],
    configuration_space={"temperature": [0.0, 0.2]},
)
def extract_invoice(text: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(
        f"Extract invoice_id, amount_due, and due_date as JSON from:\n{text}",
        model="gpt-4o-mini",
        temperature=cfg["temperature"],
    )
```

If you need weighted objective schemas, verify the exact `ObjectiveSchema` and `ObjectiveDefinition` import path against the installed SDK first. The public examples should prefer plain objective lists unless weights are essential.

## Multi-objective patterns

Use `accuracy + cost` as the default two-objective pattern for LLM tasks. It keeps the baseline quality target visible while discouraging expensive wins that are not worth the difference.

| Pattern | Use |
|---|---|
| `["accuracy"]` | Early correctness tuning with a fixed budget outside the objective. |
| `["accuracy", "cost"]` | Default for answer quality where spend matters. |
| `["accuracy", "latency"]` | User-facing online flows where response time matters. |
| `["valid_schema", "accuracy", "cost"]` | Extraction tasks with machine-checkable output format. |
| `["success_rate", "cost"]` | Tool or agent workflows where execution success is the main signal. |

Treat safety properties as constraints or gates when a violation is unacceptable. Do not let a safety score be traded away for better average accuracy or lower cost. Hand off to the relevant gate/release policy skill when the user needs approval semantics.

## Claim scope

- Metric choice determines what the optimizer can see; it is not proof that unmeasured properties improved.
- Built-in metrics are useful only when their definitions match the product claim.
- LLM-based quality scores are model opinions under a rubric. Label them that way.
- Multi-objective results depend on the dataset, objective names, and run budget used for that optimization.

## See Also

- `traigent-build-evaluator` - next step after choosing the metric
- `traigent` Step 3.5 - lightweight evaluator sanity gate (known-good/known-bad assertion before first real run)
- `traigent-decorator-setup` - wiring objectives and evaluation options into the decorator
- `traigent-analyze-results` - reading trial metrics and reporting outcomes

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
