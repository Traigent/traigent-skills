---
name: traigent-eval-build
description: "Build Traigent evaluators and scoring code. Use when wiring eval_dataset, scoring_function, metric_functions, custom_evaluator, ExampleResult, BaseEvaluator subclasses, deterministic checks, LLM judges, statistical repeated evaluations, hybrid evaluators, or fixing tuple-return/custom-scorer pitfalls."
license: Apache-2.0
metadata:
  traigent-audience: sdk-user
  traigent-topic: agent-optimization
  traigent-stage: evaluation
  traigent-maturity: stable
  author: Nimrod
  version: "1.0.22"
---

# Traigent Build Evaluator

## When to Use

Use this skill after the metric is chosen and the user needs concrete evaluator code.

- For metric selection first, use `traigent-eval-choose-metric`.
- Mock/offline check before paid runs with `TRAIGENT_OFFLINE_MODE`, `enable_mock_mode_for_quickstart()`, and a tiny local dataset.
- Ask for explicit approval and set `TRAIGENT_RUN_COST_LIMIT` before any evaluator calls paid LLMs or backend services. For custom evaluators that make several calls per row, see the cost-metering caveat in `references/evaluator-templates.md`: on traigent <= 0.29.0 only the first LLM call per row is metered, fixed in 0.30.0.
- Whether a judge call placed inside `metric_functions` is in the SDK's cost ledger depends on the SDK version and on capture: on 0.27.0 the local evaluator settled an example's cost from the agent's captured responses before it called your metric functions, so a judge call there was **not** metered (Traigent/Traigent#2297); on 0.30.0 a judge response captured through the SDK's interceptor (for example a litellm call) is folded into the example's recorded cost, with capture isolated per evaluation so concurrent trials do not drain each other's responses (ContextVar capture scopes, Traigent#2387); calls outside capture, such as an uninstrumented client, are still not counted. `TRAIGENT_RUN_COST_LIMIT` admits trials on the recorded cost and is an SDK ledger, not provider enforcement. Budget judge calls as their own line (calls per scored row × price × rows × trials), cap them in your own code, and never rely on the SDK limit to stop judge spend.
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
| 5 | `BaseEvaluator` subclass | not wireable through `@traigent.optimize` (every traigent release through 0.30.0) | The `custom_evaluator=` evaluation option accepts only a `(func, config, example)` callable and the decorator's `evaluator=` accepts only an external-service evaluator. Tier 4 is the highest tier you can wire today. |

The built-in `latency` metric uses the bare key `latency`, reported in milliseconds on SDKs after 0.22.0 (see version-matrix: `latency-unit`).

A `custom_evaluator` does not produce `latency`. If `latency` is an objective, put `metrics["latency"]` (milliseconds) on every `ExampleResult`, or the objective reads 0.0 on every trial and silently ranks nothing. `ExampleResult.execution_time` is in seconds, so convert before copying it across.

**No `expected_output` at all?** Tiers 1-3 assume a gold label to compare against. For
subjective/generative tasks with no labels, skip straight to Tier 4 with the **"LLM judge with
rubric, strict parse, and cost guardrails"** template in `references/evaluator-templates.md`
(call `build_reference_free_judge_prompt` in place of `build_judge_prompt`: same call shape, so nothing else changes once you set its `TASK_RUBRIC`; it grades against your rubric and the source instead of an `expected` answer) —
and treat `traigent-eval-audit` as mandatory, because the judge owns the whole quality
signal (see `traigent-eval-choose-metric` → "The no-gold track").

### Tier 2: scoring function

```python
import traigent
from traigent.api.decorators import EvaluationOptions

def exact_match_score(output, expected) -> float:
    # SDK builtin accuracy is case-insensitive + whitespace-trimmed (since SDK #1473)
    return 1.0 if str(output).strip().lower() == str(expected).strip().lower() else 0.0

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
    import litellm  # pip install "traigent[integrations]>=0.24.0"
    resp = litellm.completion(model=cfg.get("model", "gpt-4o-mini"), temperature=cfg["temperature"],
                              messages=[{"role": "user", "content": question}])
    return resp.choices[0].message.content
```

### Tier 3: metric functions

```python
import json

import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

def valid_json_metric(output, expected, input_data) -> float:
    try:
        json.loads(output)
    except json.JSONDecodeError:
        return 0.0
    return 1.0

def expected_field_metric(output, expected, input_data) -> float:
    # Model output that is not a JSON object is a wrong answer: score 0.0.
    # A gold that is not a dict is a dataset defect: let it raise. On 0.27.0 an
    # objective metric that raises fails the trial closed with a distinct
    # EvaluationError instead of a fake 0.0 the search would rank as "wrong answer".
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return 0.0
    if not isinstance(data, dict):
        return 0.0
    return 1.0 if data.get("label") == expected["label"] else 0.0

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/extraction.jsonl",
        metric_functions={
            "valid_json": valid_json_metric,
            "label_accuracy": expected_field_metric,
        },
    ),
    # Custom metric names need a declared orientation; only built-ins such as
    # accuracy, cost and latency have one.
    objectives=ObjectiveSchema.from_objectives([
        ObjectiveDefinition(name="label_accuracy", orientation="maximize", weight=1.0),
        ObjectiveDefinition(name="valid_json", orientation="maximize", weight=1.0),
    ]),
    configuration_space={"temperature": [0.0, 0.2]},
)
def extract(text: str) -> str:
    cfg = traigent.get_config()
    import litellm  # pip install "traigent[integrations]>=0.24.0"
    resp = litellm.completion(model=cfg.get("model", "gpt-4o-mini"), temperature=cfg["temperature"],
                              messages=[{"role": "user", "content": text}])
    return resp.choices[0].message.content
```

#### Binding a per-example side field (e.g. `db_path`) — name a `metadata` parameter

`metric_functions` binds its arguments **by parameter name**, not by position (SDK
`evaluators/local.py` `_build_metric_keyword_arguments`). The names available are:
`output`/`expected` (the row's prediction + gold), `input_data` (the **nested `input` dict only**),
`metadata` (the row's top-level extras), `llm_metrics` (alias `metrics`: this example's usage, see
"Ranked or selected outputs" below), `config`, `example`, and `example_index`.

For optional `surrogate_evaluator` mechanics and caveats, see `traigent-setup-decorator` -> "Evaluation Setup".

The documented `(output, expected, input_data)` signature **cannot** see a top-level side field like
`db_path` — `input_data` is only the `input` dict. To reach it, **name a `metadata` parameter** and
read the key the dataset contract routed there (see `traigent-dataset-curate` for the row mapping):

```python
from text2sql.execaccuracy import execution_accuracy  # opens metadata["db_path"], runs pred vs gold
from traigent.core.objectives import ObjectiveDefinition, ObjectiveSchema

def exec_acc(output, expected, metadata) -> float:   # NAME the param `metadata`
    return execution_accuracy(output, expected["sql"], metadata["db_path"])

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset="eval/salesco_30.jsonl",        # rows: {"input": {...}, "output": {"sql": "<gold>"}, "db_path": "..."}
        metric_functions={"exec_acc": exec_acc},     # Tier 3 — no climb to Tier 4 needed
    ),
    objectives=ObjectiveSchema.from_objectives([
        ObjectiveDefinition(name="exec_acc", orientation="maximize", weight=1.0),  # custom name: declare it
    ]),
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def to_sql(question: str, schema: str = "", db_id: str = "") -> str:
    ...
```

A param named `input_data` would receive the nested `input` dict, **not** `db_path` — that is the
silent trap. (Tier-4 alternative: read `example.metadata["db_path"]` directly inside a
`custom_evaluator`.)

### Ranked or selected outputs (recall at a budget)

Some agents return a **ranked list under a budget** — which tests or jobs to run, which documents to
retrieve. Score the list itself, not a string match against it:

- **Row shape.** `expected_output` is the set of items that truly matter (the failing tests); per-item
  costs and the budget are row side fields, so they reach the scorer as `metadata` — never pack them
  into the gold JSON.
- **Metric.** Walk the agent's list in order, charge each item its cost, stop at the first item that
  does not fit, and report the share of `expected_output` found (recall at budget). Precision at
  budget is the same walk divided by the items taken.
- **Not-run or unknown items.** An item with no cost in `metadata` is not run: it spends nothing and
  finds nothing, so padding a list with invented ids cannot help. Count the unknown ones in a second
  metric if they matter. A row with no expected items has no recall: raise, and keep it out of this
  metric.
- **Compare at equal cost.** Name a parameter `llm_metrics` (or `metrics`) to receive this example's
  usage: `total_cost` (USD, **`None` when unmeasured**), `total_tokens`, `prompt_tokens`,
  `completion_tokens`, `response_time_ms`. Charge model spend against the same budget as the items
  (`secs_per_usd` below); `None` raises, because unmeasured spend must not read as free.

```python runnable
def recall_at_budget(output, expected, metadata, llm_metrics) -> float:
    """Share of the items in `expected` that the ranked `output` reaches within the budget.

    metadata: {"secs": {item: seconds}, "budget": seconds, "secs_per_usd": seconds per USD}
    llm_metrics["total_cost"]: this example's model spend in USD, None when unmeasured.
    """
    if not expected:
        raise ValueError("no expected items: recall is undefined, keep this row out of the metric")
    spend = llm_metrics["total_cost"]
    if spend is None:
        raise ValueError("model spend is unmeasured: it cannot be charged against the budget")
    remaining = metadata["budget"] - spend * metadata["secs_per_usd"]
    found, seen = 0, set()
    for item in output:
        if item in seen:               # a repeated item is not run twice
            continue
        seen.add(item)
        seconds = metadata["secs"].get(item)
        if seconds is None:            # not run: spends nothing, finds nothing
            continue
        if seconds > remaining:        # the list's order is the agent's commitment
            break
        remaining -= seconds
        found += item in expected
    return found / len(expected)


meta = {"secs": {"a": 10, "b": 20, "c": 30}, "budget": 40, "secs_per_usd": 100}
assert recall_at_budget(["a", "b"], ["a", "c"], meta, {"total_cost": 0.0}) == 0.5
```

Wire it as `metric_functions={"recall_at_budget": recall_at_budget}` and declare the objective by name
(see "Tier 3"). Rows look like `{"input": {...}, "expected_output": ["a", "c"], "secs": {...},
"budget": 40, "secs_per_usd": 100}`; every key except `input` and the gold key lands in `metadata`.

### Tier 4: custom evaluator

```python
import json
import os
from pathlib import Path
import time

import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.api.types import ExampleResult


def _example_id(example) -> str:
    # Every row needs a stable, unique top-level "id" (it lands in example.metadata["id"]);
    # assign and check them at dataset prep (see "Dataset prep: stable unique row ids" in SKILL.md).
    # Hashing the content cannot tell identical rows apart, and two rows with one id overwrite each
    # other's result. Fail closed rather than invent an id.
    explicit = example.metadata.get("id")
    if explicit is None or str(explicit) == "":
        raise ValueError("dataset row has no 'id': assign stable unique row ids at dataset prep")
    return str(explicit)


def dataset_path(relative: str) -> str:
    """The absolute path the SDK loads: a relative path resolves under TRAIGENT_DATASET_ROOT, else the cwd."""
    root = Path(os.environ.get("TRAIGENT_DATASET_ROOT") or Path.cwd()).expanduser()
    return str((root / relative).resolve())


def check_row_ids(path: str) -> None:
    """Call once at import, before any model call: every row needs a unique top-level id."""
    seen: dict[str, int] = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        nested = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        row_id = row.get("id")
        # A nested metadata.id is invisible to SDKs before 0.28 and overrides "id" on newer ones,
        # so the top-level id is required and any nested id must equal it.
        if row_id is None or str(row_id) == "":
            raise ValueError(f"{path}:{number} has no top-level 'id': run assign_row_ids first")
        if "id" in nested and str(nested["id"]) != str(row_id):
            raise ValueError(f"{path}:{number} has conflicting ids (top-level vs metadata.id)")
        if str(row_id) in seen:
            raise ValueError(f"{path}:{number} repeats id {row_id!r} from line {seen[str(row_id)]}")
        seen[str(row_id)] = number

# Validate the whole dataset once, before any model call (the evaluator below fails closed per row).
DATASET = dataset_path("eval/qa.jsonl")
check_row_ids(DATASET)

@traigent.optimize(
    evaluation=EvaluationOptions(
        eval_dataset=DATASET,
        custom_evaluator=evaluate_answer,
    ),
    objectives=["accuracy"],
    configuration_space={"temperature": [0.0, 0.3]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    import litellm  # pip install "traigent[integrations]>=0.24.0"
    resp = litellm.completion(model=cfg.get("model", "gpt-4o-mini"), temperature=cfg["temperature"],
                              messages=[{"role": "user", "content": question}])
    return resp.choices[0].message.content
```

### Tier 5: BaseEvaluator subclass (not wireable today)

Do not write a `BaseEvaluator` subclass to plug into `@traigent.optimize`: no public option accepts one (every traigent release through 0.30.0). Passing an instance as the `custom_evaluator=` evaluation option fails validation with `Input should be callable`, and passing the class fails with `custom_evaluator must accept (func, config, example)`. The top-level `custom_evaluator=` argument of `@traigent.optimize` and of `optimize_sync()` accepts an instance at first, then fails when the run starts with `custom_evaluator must be callable`. The decorator's `evaluator=` takes only an external-service evaluator. Use a Tier 4 `custom_evaluator` for per-row control (calling the function, timing, judges, repeats, fail-closed handling).

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
- A row that carries its own `metadata` object changes shape at 0.28.0 (Traigent/Traigent#1768). On `traigent>=0.28.0` it is **merged** into `example.metadata`, so `example.metadata["db_id"]` works — and on a key collision the nested value silently wins over the row's top-level key of the same name. On 0.24.0-0.27.0 it nests one level down: `db_id` is at `example.metadata["metadata"]["db_id"]`, `example.metadata.get("db_id")` reads `None` and `example.metadata["db_id"]` raises `KeyError`. Read both shapes if your code must run on both sides of 0.28.0.

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

## Dataset prep: stable unique row ids

**Only the custom-evaluator templates need this.** The built-in flows (`eval_dataset` with the
default accuracy, a `scoring_function`, `metric_functions`) work on id-less rows exactly as before;
the SDK numbers those rows itself. The Tier 4 evaluator and the templates in
`references/evaluator-templates.md` return an `ExampleResult`, and its `example_id` has to be a
stable, unique id for each row. Give every row a top-level `"id"` when you build or curate the file
(`traigent-dataset-curate` writes them), or run `assign_row_ids` once on an existing id-less file.

Why: the outcome matrix keys cells by `example_id`, so two rows that share one id overwrite each
other's cell locally (SDK `traigent/utils/outcome_matrix.py:293-303`). The id sent to the backend is
a different thing: `traigent/core/metadata_helpers.py:637-645` canonicalizes customer ids by row
position, so a duplicate does not become a duplicate on the wire, but your local analysis is still
corrupted. Do not derive ids by hashing row content: identical or near-identical rows (repeated
prompts, same input with different labels) hash alike and cannot be told apart. Assign ids once and
keep them when rows are reordered or edited.

The check requires a **top-level** `"id"` on every row. A nested `metadata.id` is not enough: SDKs
before 0.28 keep a row's own `metadata` object nested (`example.metadata["metadata"]["id"]`), so the
evaluator would not see it, while on newer SDKs it is merged over the top-level key and overrides
`id`. So the check rejects a missing, null or empty top-level id, a nested id that differs from the
top-level one, and any repeat; `assign_row_ids` promotes a valid nested id to the top level (it never
renumbers it) and mints ids only for rows that have none.

Validation and loading must read the **same file**. `dataset_path()` resolves a relative path the way
the SDK does (under `TRAIGENT_DATASET_ROOT`, else the current directory), and each custom template
passes that one absolute path to both `check_row_ids` and `eval_dataset`, once at import, so the whole
dataset is validated before the first model call; if prep was skipped the run stops there, not after
paid calls. Run `assign_row_ids(dataset_path("eval/qa.jsonl"))` once to prepare an existing file.

```python
import json
import os
from pathlib import Path


def assign_row_ids(path: str, prefix: str = "row") -> None:
    """One-time: give every row a top-level id (promote a valid nested metadata.id, else mint one)."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

    def nested_id(row):
        nested = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        return nested.get("id") if nested.get("id") not in (None, "") else None

    for row in rows:
        if row.get("id") in (None, "") and nested_id(row) is not None:
            row["id"] = nested_id(row)  # promote, never renumber
    used = {str(r["id"]) for r in rows if r.get("id") not in (None, "")}
    counter = 0
    for row in rows:
        if row.get("id") in (None, ""):
            counter += 1
            while f"{prefix}-{counter:05d}" in used:
                counter += 1
            row["id"] = f"{prefix}-{counter:05d}"
            used.add(row["id"])
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def dataset_path(relative: str) -> str:
    """The absolute path the SDK loads: a relative path resolves under TRAIGENT_DATASET_ROOT, else the cwd."""
    root = Path(os.environ.get("TRAIGENT_DATASET_ROOT") or Path.cwd()).expanduser()
    return str((root / relative).resolve())


def check_row_ids(path: str) -> None:
    """Call once at import, before any model call: every row needs a unique top-level id."""
    seen: dict[str, int] = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        nested = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        row_id = row.get("id")
        # A nested metadata.id is invisible to SDKs before 0.28 and overrides "id" on newer ones,
        # so the top-level id is required and any nested id must equal it.
        if row_id is None or str(row_id) == "":
            raise ValueError(f"{path}:{number} has no top-level 'id': run assign_row_ids first")
        if "id" in nested and str(nested["id"]) != str(row_id):
            raise ValueError(f"{path}:{number} has conflicting ids (top-level vs metadata.id)")
        if str(row_id) in seen:
            raise ValueError(f"{path}:{number} repeats id {row_id!r} from line {seen[str(row_id)]}")
        seen[str(row_id)] = number
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

> **Every trial fails or scores 0.0?** First check whether the scorer returns a tuple such as
> `(score, reason)` instead of a float. On SDK 0.33.0 a tuple from a `scoring_function` /
> `metric_functions` scorer fails the trial with `float() argument must be a string or a real
> number, not 'tuple'` ("All trials failed"); return the float and put the reason elsewhere.

## Known pitfall: tuple returns and custom scorers

If the optimized function returns `(output, metrics)`, make sure the custom scorer receives the model output, not the whole tuple, unless your scorer intentionally handles tuples. Prefer one of these patterns:

- Keep the production function returning the plain output, and collect extra metrics inside `custom_evaluator`.
- If returning `(output, metrics)`, unwrap before string comparison, JSON parsing, or label matching.
- Do not reuse a metric name for both tuple-returned metrics and evaluator-computed metrics.

## Known pitfall: arbitrary gold ordering caps accuracy

When a deterministic scorer compares structured outputs against a gold whose internal ordering is arbitrary (SQL projection columns, JSON object keys, set-valued answers), decide the order policy explicitly and write it in the evaluator docstring. If the gold's ordering is arbitrary and the comparator is positional, correct answers score 0 and impose a hard accuracy ceiling that no configuration can cross — the optimizer then ranks knobs by their accidental effect on ordering. Policy for SQL execution match (the Spider test-suite convention): row order significant only when gold has `ORDER BY`; column order never significant (compare under column permutations); column count must match. Audit signal: an example that fails in 100% of trials across all configs is a metric-artifact suspect — re-check its gold and your order policy before blaming the model.

## Known pitfall: score what the evaluator is handed, not what the model meant

A chat model wraps code, SQL, and JSON in a markdown fence by default — and sometimes when told not to. An exact or normalized comparator scores that reply 0 for every configuration, so every candidate ties and the search ranks noise. Put the agent's own extraction step (fence strip, first statement, JSON parse) between model and scorer, then pass a known-right answer through that step and confirm it still scores right. A first paid run whose primary metric is exactly 0.0 or 1.0 on every trial is a scorer-or-extraction suspect: dump one raw reply and the value the scorer received before spending again.

## Claim scope

- Deterministic scores measure only the rules encoded in the evaluator.
- A metric's 0.0 must mean the answer was wrong; a harness or data-shape failure must raise or be flagged, never scored as an ordinary wrong answer without being counted separately (the judge template's parse-failure 0.0 is such a counted class).
- Judge scores are model opinions under the stated rubric. Label them as judge scores.
- Statistical scores depend on repeat count, sampling settings, and dataset slice.
- Hybrid scores inherit both the deterministic gate assumptions and judge limitations.

## See Also

- `traigent-eval-choose-metric` - choose objectives before building evaluator code
- `traigent-boost-agent` Step 3.5 - lightweight evaluator sanity gate (run this before the first paid optimization)
- `traigent-eval-audit` - evaluator reliability: manual gold-slice protocol + service-side evaluator-audit action (no new gold collection required)
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
import asyncio
policy = None
try:
    policy = asyncio.run(client.get_interaction_policy(skill="<this skill>"))
except Exception:
    pass
# Inside an async function (an event loop is already running), use
#   policy = await client.get_interaction_policy(skill="<this skill>")
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
- Recommend the next skill only after a result-bearing step (a run finishes, an analysis
  completes, a configuration validates) or an explicit decision point. Omit recommendations
  during setup or mid-walkthrough. Cap at 3 recommendations per response, each on its own line
  with a one-line eligibility reason (e.g., "traigent-analyze-results — ✓ run succeeded" or
  "traigent-optimize-run — ✓ config validated").
- When the user asks which Skills were used, answer briefly from what the session establishes: name the
  relevant Skills actually consulted, any that were unavailable, and any relevant deferred step with its
  reason. Keep installed availability, consultation and user-directed selection distinct, and never infer
  absence from non-use. Example: "Consulted quickstart and eval-build; post-run analysis is deferred
  because no optimization result exists." Do not volunteer this unasked.
- Never weaken Traigent safety: dry-run before any paid run; get explicit approval before real cost
  or before any data leaves the machine; treat service-returned plans and next steps as
  authoritative. Never put the persona profile or any private content into telemetry, run metadata,
  experiment names, logs, or provenance files.
<!-- /INTERACTION_POLICY v1 -->
