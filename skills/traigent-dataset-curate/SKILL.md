---
name: traigent-dataset-curate
description: "Create and improve a Traigent evaluation dataset / JSONL eval set. Use when asked to create an evaluation dataset, check whether examples are good enough, synthesize more examples, grow a dataset, score examples after a run, inspect dataset quality, design a holdout split, avoid leakage in eval data, reflect on hard examples, work through server-flagged hard or broken example IDs, map flagged example IDs to local content, or run the content-reflection loop after a run."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.1.1"
---

# Traigent Curate Dataset

## When to Use

Requires `traigent>=0.16.0`.

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
See `traigent-eval-build` for the scorer that reads a per-example `metadata` field.

**No ground-truth labels to put in the gold key?** For subjective/generative tasks (summaries,
chat, open-ended agents), curation still applies — it just produces different assets: a
representative, stratified set of **inputs**, a **rubric** with anchored score levels (and
optionally a few reference outputs as calibration anchors, clearly marked as references, not
gold). The score then comes from an LLM judge, not a label comparison — follow
`traigent-eval-choose-metric` → "The no-gold track" and `traigent-eval-build`'s judge template,
and treat `traigent-eval-audit` as mandatory. Holdout discipline below applies unchanged:
the judge's calibration examples must stay out of the holdout.

Holdout rules:

- Split by stable example id, customer, document, repository, or time window when near-duplicates exist.
- Stratify by task type, difficulty, language, tenant, tool path, and known failure class.
- Keep synthetic examples out of the holdout unless a human reviews and labels them independently.
- Rebuild the tuning slice freely; touch the holdout only to add newly sourced, independently reviewed examples.
- Report tune-slice movement and holdout movement separately.

## Synthesize examples client-side with no backend egress

Use client-side synthesis when data is sensitive, labels need local review, or the user has not approved a backend run. Passing your own `llm` keeps synthesis on the user's LLM path. Tag synthetic rows in metadata and keep the seed ids.

```python
import litellm

from traigent.evaluators import Dataset
from traigent.generation import DatasetGrowthOptions, ExampleSynthesizer, GuidanceAction

def private_llm(prompt: str) -> str:
    response = litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

seed_dataset = Dataset.from_jsonl("eval/tune.jsonl")

growth_options = DatasetGrowthOptions(
    examples_per_round=6,
    max_total_examples_added=30,
)
synthesizer = ExampleSynthesizer(
    llm=private_llm,
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
import litellm
import traigent
from traigent.api.decorators import EvaluationOptions
from traigent.generation import DatasetGrowthOptions
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()

def prompt_model(prompt: str, *, temperature: float = 0.0) -> str:
    response = litellm.completion(
        model="gpt-4o-mini",
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

@traigent.optimize(
    evaluation=EvaluationOptions(eval_dataset="eval/tune.jsonl"),
    objectives=["accuracy", "cost"],
    configuration_space={"temperature": [0.0, 0.3, 0.7]},
)
def answer(question: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(question, temperature=cfg["temperature"])

growth_options = DatasetGrowthOptions(
    examples_per_round=4,
    max_total_examples_added=12,
)

# `guidance_provider` and `weak_examples` are NOT defined here — they come
# from your prior run: the service next-step payload (see `traigent-analyze-guidance`)
# supplies the provider, and the flagged/weak example ids come from that
# payload or your own analysis (see "Reflect on Hard Examples" below).
results = answer.optimize_with_guidance(
    provider=guidance_provider,      # from the traigent-analyze-guidance payload
    rewrite_llm=prompt_model,
    grow_dataset=growth_options,
    weak_examples=weak_examples,     # flagged example ids from the prior run
    max_trials=8,
)
```

## Reflect on Hard Examples (Server-Flagged)

Requires `traigent>=0.16.0`.

Use this after a Traigent run when the server has identified hard, weak, or
broken examples and the user wants to improve the agent, prompt, skill, or
dataset using local example content. This is the content-reflection loop:
Traigent can identify safe example ids and coarse categories, but raw example
content stays local. The skill joins those ids to local inputs, expected
outputs, and actual outputs, then takes one server-suggested action.

### Boundary

The server selects the examples and recommends the next action. This skill
does not decide which examples are hard.

- Fetch flagged ids and coarse categories from server surfaces such as
  `traigent next-steps RUN_ID --json` and example-scoring dataset-quality
  output (see "Score examples after a run" above).
- Do not rank, expand, or replace the flagged id list locally.
- Do not send raw example text, expected answers, actual answers, traces, or
  customer content to Traigent unless the user explicitly approves that
  egress.
- If the server returns no flagged ids, stop or ask the user whether to run
  the server-side scoring/recommendation flow. Do not make a local
  hard-example list.
- Take one action from the server recommendations. If the user wants another
  action, label it as a manual override or request refreshed next steps.

### Protocol

1. Fetch the server payload. Prefer `traigent next-steps RUN_ID --json`; if
   the flow is already in example-scoring, use the server's dataset-quality
   or curation output (see "Score examples after a run" above). Record the
   returned ids, coarse categories, and recommended actions exactly.
2. Build a local example-content map: use `traigent report-example-map` for a
   local-only file map from dataset rows to stable example ids, or the SDK
   helper `build_example_content_map` when already inside Python automation.
3. Join only the server-flagged ids to local content. For each matched id,
   read: input, expected output, actual output from the run artifact, the
   coarse category returned by the server, and any local metadata such as
   split, source, or reviewer note.
4. Classify the local failure pattern from expected-vs-actual, keeping the
   classification factual and content-local — e.g. label mismatch, missing
   context, retrieval miss, tool-use failure, output-format failure, prompt
   ambiguity, evaluator issue, or agent-code bug. If the classification is
   "evaluator issue", the server next-step may be a server-side evaluator
   audit (ACET-based, read-only) or `improve_evaluator` (lockbox repair);
   present the server action verbatim and hand off to
   `traigent-eval-audit` — do not manually re-rank or re-score
   evaluators.
5. Pick exactly one server-suggested action and ask the user to approve it:
   `ExampleSynthesizer` with `GuidanceAction.GENERATE_HARDER` or
   `GENERATE_SIMILAR`, or `optimize_with_guidance(grow_dataset=...,
   weak_examples=...)` — see "Synthesize examples client-side with no backend
   egress" above for the exact call patterns — a prompt rewrite, a trained
   skill, or a fix to the agent code.
6. Execute the approved action locally. For generated or changed examples,
   mark them for human label review before they can support a holdout claim.
7. Loop back to `traigent-analyze-guidance` for a fresh service plan. Do not launch a
   new optimization run from this skill without the run-plan confirmation and
   mock dry-run flow.

### Local Report

Return a compact local report to the user: run id and portal link; server
source used for flagged ids; number of server-flagged ids and number matched
locally; coarse categories returned by the server; local failure-pattern
classifications with ids, not raw private content unless the user approves
showing it; the single approved action taken; files changed or examples
generated; any egress approval or denial; next `traigent-analyze-guidance` context.

### Privacy And Egress

The local content map can contain proprietary examples. Store it in the
project workspace or another user-approved local path, avoid committing it by
default, and delete temporary maps when the user asks. Share only safe ids
and aggregate counts with Traigent unless the user explicitly approves
sending example text.

## Synthesize via the Traigent backend

Backend dataset generation requires a Traigent account/backend and configured credentials such as `TRAIGENT_API_KEY` and `TRAIGENT_BACKEND_URL`. If you have not yet set up `TRAIGENT_API_KEY`, see [Getting your Traigent API key](../traigent-setup-quickstart/SKILL.md#get-your-traigent-api-key).

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
Important honesty point: the backend redacts proprietary scoring signals. The client receives non-signal metadata such as example ids, sample counts, algorithm version, scored flags, and quality-job status. Do not teach or infer hidden difficulty, informativeness, or ambiguity values from the client response. The ranked and flagged "examples to review" surface (`analytics_get_example_insights` / `GET /api/v1/analytics/runs/{run_id}/example-insights`) is likewise non-signal: it conveys review urgency, enum flags, and a suggested action — never raw scores, formulas, or composite values.
<!-- /PROTECTED -->

> **Import note (verified against SDK 0.18.x):** `ExampleInsightsClient` ships in the core SDK at `traigent.analytics` — no separate install required. The `traigent.analytics` module docstring recommends the separate `traigent-analytics` plugin (`pip install traigent-analytics`), but that plugin's public API (meta-learning, predictive analytics, anomaly detection, cost optimization, scheduling — see its own `__all__`) does not include `ExampleInsightsClient`; `from traigent_analytics import ExampleInsightsClient` raises `ImportError`. Use the core import below and ignore the module's `DeprecationWarning` for this class specifically. **Caveat if you HAVE installed the plugin:** the core shim then defers to the plugin and stops exposing this class, so `from traigent.analytics import ExampleInsightsClient` itself raises `ImportError` — either uninstall the plugin (`pip uninstall traigent-analytics`) or use the deep import `from traigent.analytics.example_insights import ExampleInsightsClient`, which works with or without the plugin (verified).

```python
from traigent.analytics import ExampleInsightsClient

async def compute_example_scores(run_id: str) -> dict:
    # compute_scores/get_job_status/get_example_scores/get_dataset_quality are
    # all async — await each one (a common mistake is calling them unawaited
    # at module scope, which yields un-subscriptable coroutine objects).
    async with ExampleInsightsClient(
        backend_url="https://traigent.example",
        api_key="uk_...",
    ) as client:
        job = await client.compute_scores(run_id)
        status = await client.get_job_status(job["job_id"])
        scores = await client.get_example_scores(run_id, example_ids=["ex_001", "ex_002"])
        quality = await client.get_dataset_quality(run_id)
        return {"status": status, "scores": scores, "quality": quality}
```

Example-scoring endpoints:

| Endpoint | Use |
|---|---|
| `POST /api/v1/analytics/example-scoring/{run_id}/compute` | Start scoring for a completed run. |
| `GET /api/v1/analytics/example-scoring/{run_id}/scores` | Read per-example scoring metadata. |
| `GET /api/v1/analytics/example-scoring/{run_id}/dataset-quality` | Read dataset-level quality metadata. |
| `GET /api/v1/analytics/runs/{run_id}/example-insights` | Read ranked and flagged examples to review (IP-safe: review_priority, suspicious_flags, recommended_action). |

### Examples to review (ranked & flagged)

When a run completes, the `analytics_get_example_insights` MCP tool (or `GET /api/v1/analytics/runs/{run_id}/example-insights`) returns up to 100 examples ranked by review urgency — no raw scores or formulas are exposed. The summary includes `dataset_quality` (low | medium | high) and flag-type counts. Each example row carries:

| Field | Values |
|---|---|
| `safe_example_ref` | Opaque hashed ref (`exref_...`) — not a raw id or content |
| `review_priority` | critical \| high \| medium \| low — review urgency, not a quality score |
| `difficulty_bucket` | low \| medium \| high \| unknown — coarse bucket only |
| `suspicious_flags` | See flag-to-action table in the improve loop below |
| `recommended_action` | review_label \| clarify_expected_output \| increase_repetitions \| replace_or_rewrite \| keep_as_hard_case \| remove_redundant \| inspect_evaluator |

## The improve loop

1. Run a mock/offline smoke check.
2. Run a small tuning pass with a fixed tuning slice and explicit cost limit.
3. Pull examples to review from `GET /api/v1/analytics/runs/{run_id}/example-insights` (MCP: `analytics_get_example_insights`); work them in `review_priority` order and act on each `suspicious_flag` using the table below.
4. Synthesize harder or more diverse examples around those weak examples.
5. Human-review synthetic labels and metadata before adding them to the tuning slice.
6. Re-run on the enlarged tuning slice.
7. Validate once on the untouched holdout slice.
8. Report tune and holdout results separately, including failed trials and cost.

Flag-to-curation-action guide for step 3:

| Flag | Curation action |
|---|---|
| `possible_mislabel` | Re-check the expected answer / rubric |
| `redundant_pattern` | Remove or dedupe; broaden coverage elsewhere |
| `anomalous_low_success` | Clarify the expected output, or keep as a deliberate hard case |
| `high_response_variance` | Clarify acceptable answers or add repetitions |
| `low_agent_strength_correlation` | Review the label or the evaluator for this example |
| `low_sample_support` | Rerun for more evidence before a permanent dataset change |

## Claim scope

- Dataset quality statements are observations about the reviewed evaluation dataset, labels, split, and scoring method.
- Synthetic examples are useful coverage candidates until reviewed; do not treat them as independent holdout evidence.
- Backend example-scoring client output is non-signal metadata. Do not describe redacted proprietary signals as available.
- Backend example-scoring (via `ExampleInsightsClient`) reports properties of examples. Evaluator-quality audit (ACET, via the server-side evaluator-audit action) reports properties of evaluators. These are separate surfaces — scoring a dataset does not validate the evaluator, and auditing the evaluator does not score the dataset.
- Ranked and flagged "examples to review" rows (from `analytics_get_example_insights` / `GET /api/v1/analytics/runs/{run_id}/example-insights`) are non-signal: they convey review urgency (`review_priority`), enum flags (`suspicious_flags`), and a suggested action (`recommended_action`) — not quality scores, formulas, or composite values.
- A holdout result supports a claim only for the task distribution represented by that holdout slice.

## See Also

- `traigent-setup-quickstart` - mock/offline setup and first optimization run
- `traigent-eval-choose-metric` - choosing objectives before labeling examples
- `traigent-eval-build` - implementing scoring functions and custom evaluators
- `traigent-boost-agent` - end-to-end optimization workflow for an existing agent
- `traigent-analyze-guidance` - fetch server recommendations
- `traigent-analyze-guidance` - fetch and confirm the next service plan
- `traigent-analyze-guidance` - local result inspection when the user requests it

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
