# What a Run Costs, and How to Keep It Safe

<!-- Generated copy: edit docs/shared/run-cost-and-limits.v1.md in the traigent-skills repo, then run python tools/contract/sync_run_cost_reference.py. -->

Show this card to the user once, before the first paid run on a project. Everything here holds
on every released Traigent SDK version, except the section marked otherwise.

## What you pay for

Traigent tries several versions of your agent ("trials"). Each trial runs your agent on the
examples in your dataset. So the number of model calls is roughly:

**trials × examples × model calls per example**, plus any calls made by an LLM judge that
grades the answers.

Worked example: 10 trials × 20 examples × 2 model calls per example = 400 calls. At $0.002 a
call (illustrative — use your model's real price) that is about $0.80. A judge that grades each
answer once adds 10 × 20 = 200 more calls. A pricier model in the search space raises the cost
of every trial that uses it.

## Guards, in this order

1. **Dry run with no provider spend.** Call `enable_mock_mode_for_quickstart()` (from
   `traigent.testing`) and declare `offline=True` on the decorated function. Simulated calls
   cost nothing and send no backend traffic. It proves the wiring, not the quality. The
   pre-run estimate and its cap (guard 2) still apply to a mock run on SDK 0.31.0+: see
   "Mock dry runs on SDK 0.31.0+" below.
2. **A spending cap.** Pass `cost_limit` in USD to `.optimize()` (or set
   `TRAIGENT_RUN_COST_LIMIT`; the default is $2.00). A pre-run estimate over the cap stops the
   run before anything is spent; a cap hit mid-run stops the run and keeps the finished trials
   (`stop_reason == "cost_limit"`). The cap is **not a hard billing ceiling**: it is enforced
   one trial at a time, so a single large trial, or trials already in flight in parallel, can
   push actual spend past it before the check runs. In an interactive terminal an over-cap
   estimate can also ask you to approve and raise the limit instead of refusing, while a
   non-interactive process refuses unless the run was already approved. If you need a billing
   guarantee, verify what your model provider can actually enforce (a project budget or an
   alert threshold is usually advisory, not an admission cap) and state any residual exposure.
   Never paste credential values into the coding-agent conversation.
3. **A size cap.** `max_trials` limits the number of trials; `max_total_examples` limits the
   examples summed over all trials. Start small.

## Cost you can't see is still billed

`cost_limit` only bounds the cost Traigent measures. Traigent measures calls made through:

- LangChain chat models called with synchronous `.invoke`
- non-streaming `litellm.completion` / `litellm.acompletion`
- Traigent's own Bedrock client

It does not reliably measure streaming calls, async LangChain (`ainvoke`, `abatch`), raw
OpenAI, Anthropic or Google SDK calls, or plain HTTP requests. Calls your evaluator or an LLM
judge makes directly may not be counted either. Your provider bills all of them, but Traigent
reports them as `$0` or as not measured (`None`), so the cap cannot stop them.

Fix: route the model call through a measured client above. For a gateway or custom model name,
give it a price with `TRAIGENT_CUSTOM_MODEL_PRICING_JSON`.

Streaming needs its own check even when the client is otherwise measured. `litellm` streaming
calls (`stream=True`) are never measured, on either `completion` or `acompletion` — usage isn't
available until your own code finishes consuming the stream. LangChain's `.stream()` /
`.astream()` capture the *last* chunk, so they are measured only when the provider puts usage in
that chunk (pass `stream_usage=True` to get it); without it, the call is unmeasured like any
other stream.

## When cost can't be measured (SDK 0.30.0+)

From SDK 0.30.0 (see version-matrix: `unmeasured-cost-cap`) an unmeasured call shows as
`None` / `n/a`, not `$0`, and the run guards itself:

- Raw OpenAI SDK calls are measured when the OpenAI override is on
  (`enable_openai_optimization()`, or `framework_targets=["openai.OpenAI", "openai.AsyncOpenAI"]`
  with `auto_override_frameworks=True`). Non-streaming calls that return `usage` only.
- If you did **not** set `max_trials` or `max_total_examples`, a run whose cost cannot be measured
  stops after **10 trials** (a safety limit; `TRAIGENT_FALLBACK_TRIAL_LIMIT` changes it). Warning:
  `COST_UNMEASURED_TRIAL_LIMIT_REACHED`.
- If you **did** set one, Traigent takes that as your OK and runs up to it. Warning:
  `COST_UNMEASURED_TRIALS_RAN`.
- Partial capture: `COST_OBJECTIVE_PARTIAL_USAGE_CAPTURED`; nothing captured with a cost
  objective: `COST_OBJECTIVE_NO_USAGE_CAPTURED` (this one exists from 0.29.0).

## Mock dry runs on SDK 0.31.0+

From SDK 0.31.0 a mock run is still priced: the pre-run estimate is computed from your dataset
and models, and the cap in guard 2 applies, so a large dataset can raise `CostLimitExceeded`
before trial 1 even though nothing would be spent. (SDKs before 0.31.0 skipped the estimate in
mock mode.) Two supported ways to dry-run a large dataset:

- **A small slice.** Point the dry run at a few rows (for example 5 to 10). This works on every
  SDK version and needs no environment variable.
- **The SDK's mock exemption.** Set `TRAIGENT_COST_PREFLIGHT_MOCK_EXEMPT=1` together with an
  explicit non-production environment (`ENVIRONMENT=development`, or `test`, `testing`,
  `local`, `dev`, `stage`, `staging`). It applies only while mock mode is on. With the
  environment unset, `ci` or production it is ignored and the estimate still applies. Use it
  for test and walkthrough runs only.

Do not set `TRAIGENT_COST_APPROVED=true` to get past a mock run's refusal. It approves spend,
and the same shell would carry that approval into the real run.

## Before a real run, check

- The mock run passed, and mock mode is off for the real run: start a fresh interpreter and
  remove `offline=True`.
- Every model call goes through a measured client listed above.
- A tiny paid probe (1–2 examples, fewest trials, cheapest model) shows `results.total_cost`
  above 0 — not `0.0`, not `None`.
- The user said yes to a dollar cap and a trial count.
- `results.total_cost` is not `None`/`n/a`.
