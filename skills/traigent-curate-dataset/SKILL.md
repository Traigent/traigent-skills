---
name: traigent-curate-dataset
description: "Create and improve a Traigent evaluation dataset / JSONL eval set. Use when asked to create an evaluation dataset, check whether examples are good enough, synthesize more examples, grow a dataset, score examples after a run, inspect dataset quality, design a holdout split, or avoid leakage in eval data."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.1"
---

# Traigent Curate Dataset

## When to Use

Use this skill when you need to build, grow, or audit the examples that Traigent uses to evaluate an optimized function.

- Start from existing fixtures, golden sets, support tickets, logs, traces, or manually labeled examples.
- Keep tuning and holdout slices separate. Never tune and claim on the same slice.
- Mock or zero-egress check first with `enable_mock_mode_for_quickstart()`, `offline=True`, and a small local sample.
- Before paid provider or backend runs, estimate cost, ask for user approval, and set `TRAIGENT_RUN_COST_LIMIT`.
- For task-shape recipes, read `references/dataset-recipes.md`.

## Assess what you already have

Inventory real examples before synthesizing:

- Fixtures and regression tests: convert inputs and expected outputs into JSONL rows.
- Golden sets: prefer examples with source links, reviewer notes, or product-owner acceptance.
- Logs and traces: sample real inputs, then redact secrets and PII before labeling.
- Failure reports: keep the original failure input, expected behavior, and the bug class in metadata.

Minimum starting counts:

| Use | Count | Notes |
|---|---:|---|
| Smoke check | 10-20 | Catch wiring, loader, and scorer mistakes. |
| First tuning slice | 30-100 | Cover the main strata and known failure modes. |
| Holdout slice | 30+ | Keep untouched until the final validation readout. |
| High-variance tasks | 100+ | Add per-stratum coverage before trusting aggregate movement. |

Prefer fewer well-labeled examples over many vague examples. Every row should have a reason to exist: common path, edge case, high-value customer path, known failure, or safety-critical path.

## JSONL format and holdout discipline

Use one JSON object per line. Put model inputs under `input` or `input_data`, the expected answer under `expected_output` or an accepted alias, and non-label context in `metadata`.

```json
{"input": {"question": "What is the refund window for annual plans?"}, "expected_output": "Annual plans are refundable within 30 days.", "metadata": {"split": "tune", "source": "policy-golden", "task": "qa"}}
{"input": {"question": "Can I pause a monthly subscription?"}, "expected_output": "Monthly subscriptions can be paused from billing settings.", "metadata": {"split": "holdout", "source": "support-review", "task": "qa"}}
```

### One canonical dataset contract

Every Traigent skill maps a JSONL row the same way — this is the single contract (quickstart's
flat `{"input": "...", "output": "..."}` is just this contract with scalar values):

| Row key | Becomes | Notes |
|---|---|---|
| `input` (or `input_data`) | `example.input_data` | required; the value can be a scalar **or a nested dict**. Called as `func(**input_data)` when it is a dict. |
| **gold key** (first match) | `example.expected_output` | the value can be a scalar **or a nested dict** (then index it, e.g. `expected["sql"]`). |
| every **other top-level key** | `example.metadata[<key>]` | this is how a **per-example side field** (e.g. `db_path`) reaches a scorer. |

**Accepted gold-key aliases**, in first-match order (SDK `evaluators/base.py` `_EXPECTED_OUTPUT_FIELDS`):
`output`, `expected`, `expected_output`, `answer`, `target`, `label`. Pick **one** per row.

So a nested, execution-scored row is fully supported:

```json
{"input": {"question": "...", "schema": "CREATE TABLE ...", "db_id": "sales"}, "output": {"sql": "SELECT COUNT(*) FROM customers;"}, "db_path": "data/sales.db"}
```

Here `input` → `example.input_data` (the nested dict), `output` → `example.expected_output`
(gold SQL is `expected["sql"]`), and the top-level `db_path` → `example.metadata["db_path"]`.
See `traigent-build-evaluator` for the scorer that reads a per-example `metadata` field.

Holdout rules:

- Split by stable example id, customer, document, repository, or time window when near-duplicates exist.
- Stratify by task type, difficulty, language, tenant, tool path, and known failure class.
- Keep synthetic examples out of the holdout unless a human reviews and labels them independently.
- Rebuild the tuning slice freely; touch the holdout only to add newly sourced, independently reviewed examples.
- Report tune-slice movement and holdout movement separately.

## Synthesize examples client-side with no backend egress

Use client-side synthesis when data is sensitive, labels need local review, or the user has not approved a backend run. Passing your own `llm` keeps synthesis on the user's LLM path. Tag synthetic rows in metadata and keep the seed ids.

```python
from traigent.evaluators import Dataset
from traigent.generation import DatasetGrowthOptions, ExampleSynthesizer, GuidanceAction

seed_dataset = Dataset.from_jsonl("eval/tune.jsonl")

growth_options = DatasetGrowthOptions(
    examples_per_round=6,
    max_total_examples_added=30,
)
synthesizer = ExampleSynthesizer(
    llm=call_private_llm,
    options=growth_options,
)

synthetic_examples = synthesizer.synthesize(
    seed_examples=seed_dataset.examples[:8],
    action=GuidanceAction.GENERATE_HARDER,
    count=6,
    seed_ids=["tune-001", "tune-014"],
    existing=seed_dataset.examples,
)

for example in synthetic_examples:
    example.metadata["review_status"] = "needs_human_label_check"
```

For guided optimization flows, grow examples from the optimized function instead of separately managing the synthesizer:

```python
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.generation import DatasetGrowthOptions
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()

@traigent.optimize(
    evaluation=EvaluationOptions(eval_dataset="eval/tune.jsonl"),
    objectives=["accuracy", "cost"],
    configuration_space={"temperature": [0.0, 0.3, 0.7]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return call_llm(question, temperature=cfg["temperature"])

growth_options = DatasetGrowthOptions(
    examples_per_round=4,
    max_total_examples_added=12,
)

results = answer.optimize_with_guidance(
    provider=guidance_provider,
    rewrite_llm=call_private_llm,
    grow_dataset=growth_options,
    weak_examples=weak_examples,
    max_trials=8,
)
```

## Synthesize via the Traigent backend

Backend dataset generation requires a Traigent account/backend and configured credentials such as `TRAIGENT_API_KEY` and `TRAIGENT_BACKEND_URL`. If you have not yet set up `TRAIGENT_API_KEY`, see [Getting your Traigent API key](../traigent-quickstart/SKILL.md#get-your-traigent-api-key).

Use backend synthesis when:

- the user approves account-backed generation,
- centralized dataset records are required,
- the team wants backend-side example storage and review workflows,
- or many collaborators need the same generated examples.

Relevant backend endpoints:

| Endpoint | Use |
|---|---|
| `POST /api/v1/datasets/generate` | Create a new generated dataset from instructions or seeds. |
| `POST /api/v1/datasets/{id}/generate-examples` | Add generated examples to an existing dataset. |
| `GET /api/v1/datasets/{id}/examples` | Read examples for review or export. |
| `POST /api/v1/datasets/{id}/examples` | Add reviewed examples. |

Prefer client-side synthesis when data-handling review is incomplete, no account is configured, or the user has not approved paid work.

## Score examples after a run

`ExampleInsightsClient` can ask the backend to compute and return example-scoring metadata for a completed run. This requires a Traigent account/backend.

<!-- PROTECTED -->
Important honesty point: the backend redacts proprietary scoring signals. The client receives non-signal metadata such as example ids, sample counts, algorithm version, scored flags, and quality-job status. Do not teach or infer hidden difficulty, informativeness, or ambiguity values from the client response.
<!-- /PROTECTED -->

> **Deprecated:** `traigent.analytics` is deprecated since SDK 0.9.0. Use the `traigent-analytics` plugin: `pip install traigent-analytics` and import from `traigent_analytics` instead. The `traigent.analytics` shim still works but emits a deprecation warning.

```python
# Canonical (traigent-analytics plugin):
from traigent_analytics import ExampleInsightsClient
# Legacy (deprecated, emits DeprecationWarning):
# from traigent.analytics import ExampleInsightsClient

client = ExampleInsightsClient(
    backend_url="https://traigent.example",
    api_key="trg_...",
)

job = client.compute_scores("run_123")
status = client.get_job_status(job["job_id"])
scores = client.get_example_scores("run_123", example_ids=["ex_001", "ex_002"])
quality = client.get_dataset_quality("run_123")
client.close()
```

Example-scoring endpoints:

| Endpoint | Use |
|---|---|
| `POST /api/v1/analytics/example-scoring/{run_id}/compute` | Start scoring for a completed run. |
| `GET /api/v1/analytics/example-scoring/{run_id}/scores` | Read per-example scoring metadata. |
| `GET /api/v1/analytics/example-scoring/{run_id}/dataset-quality` | Read dataset-level quality metadata. |

## The improve loop

1. Run a mock/offline smoke check.
2. Run a small tuning pass with a fixed tuning slice and explicit cost limit.
3. Identify weak examples from failed or low-scoring trials.
4. Synthesize harder or more diverse examples around those weak examples.
5. Human-review synthetic labels and metadata before adding them to the tuning slice.
6. Re-run on the enlarged tuning slice.
7. Validate once on the untouched holdout slice.
8. Report tune and holdout results separately, including failed trials and cost.

Planned: automatic curation-advice endpoints are not available in this SDK surface yet.

## Claim scope

- Dataset quality statements are observations about the reviewed evaluation dataset, labels, split, and scoring method.
- Synthetic examples are useful coverage candidates until reviewed; do not treat them as independent holdout evidence.
- Backend example-scoring client output is non-signal metadata. Do not describe redacted proprietary signals as available.
- A holdout result supports a claim only for the task distribution represented by that holdout slice.

## See Also

- `traigent-quickstart` - mock/offline setup and first optimization run
- `traigent-choose-metric` - choosing objectives before labeling examples
- `traigent-build-evaluator` - implementing scoring functions and custom evaluators
- `traigent-boost-agent` - end-to-end optimization workflow for an existing agent

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->
