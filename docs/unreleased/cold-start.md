# Cold start: building a first eval set when there is nothing to curate

Requires `traigent>=0.27.0`. **Unreleased today.** The currently shipping SDK is
`0.26.0` and does not contain `traigent.generation.coldstart` at all — everything
below documents an interface that exists in source but has not shipped. The
backend planning endpoint this path calls, `POST /api/v1/guidance/cold-start-plan`,
also ships behind the `ENABLE_COLD_START_GENERATION` flag and is **off by default**
even once the SDK ships it — a deployment that has not explicitly turned the flag
on returns a fail-closed `feature_disabled` gap for every call. Check the
installed `traigent.__version__` and confirm the flag with the deployment owner
before pointing a user at this path; do not present it as available today.

## When to use this — and when not to

Use this only when "Assess what you already have" above turns up nothing: no
fixtures, golden sets, support tickets, logs, traces, or manually labeled
examples anywhere in reach. Real curated data beats generated data every
time — if even a handful of usable rows exist in any of those sources, go
curate them with the rest of this skill instead of reading further.

## The honest limit: the SDK ships no technique, and no verifier

`build_cold_start_eval_set` brings **no generation technique and no
verification logic of its own**. `generator` and `verifier` are required
keyword arguments with no default — the call raises nothing and simply
refuses (see below) if either is missing:

- `generator` proposes candidate `(inputs, output)` pairs, given a candidate
  budget. How to construct a plausible input, and what output to claim for
  it, is technique the caller brings. The SDK does not synthesize inputs, and
  it never calls an LLM on your behalf.
- `verifier` is a `LocalVerifier` subclass whose `verify()` independently
  scores each candidate. Without one, there is nothing behind a row but the
  generator's own unchecked claim.

**A repository plus a decorated function is not sufficient input.** If there
is no real generation technique and no real local scoring authority, the
correct outcome is `ColdStartOutcome.DISCOVERY_ONLY`. That is not a failure
to route around with a second LLM call standing in as its own judge, or a
verifier that just echoes back whatever the generator produced — it is the
honest answer that this codebase cannot be cold-started safely yet, and
`build_cold_start_eval_set` is built to fail closed into exactly that answer
rather than hand back a fabricated eval set.

## What crosses the network — and what never does

The only network call this path makes is one `POST` to the backend's
`cold-start-plan` endpoint, made through a `transport` callable **you**
supply — the SDK never opens a connection itself. What that request carries
is a content-free descriptor built by inspecting `func`'s signature: the
parameter **count** and each parameter's **coarse type class** (`string`,
`integer`, `number`, `boolean`, `object`, `array`, or `unknown`), the return
type's coarse class, the `verifier.kind` you declared, and the
`generation_capabilities` you declared. Never sent: parameter names,
annotation text, docstrings, module or file paths, default values, prompts,
generated candidate rows, expected outputs, or verifier scores. All
candidate generation, verification, and artifact writing happen locally,
after the plan comes back — nothing generated is ever sent to the backend.

## How a call resolves

1. **Build a descriptor** from `func`'s real signature, unwrapping any
   decorator first so a `@traigent.optimize`-wrapped target is described
   correctly rather than as a zero-argument function.
2. **POST it** through your `transport` and get back a plan: a `plan_id`, a
   digest of the descriptor it was issued for, a granted `candidate_limit`
   (which may be lower than `requested_candidate_limit` and always wins), and
   an expiry. This plan is **not cryptographically signed** — it is trusted
   the same way any backend response is trusted, no more. The SDK
   recomputes the descriptor digest itself and refuses the plan if it
   doesn't match what this process actually sent.
3. **Generate and verify locally**: pull candidates from `generator` up to
   the granted limit, drop anything structurally malformed, drop anything
   that would not bind against `func`'s real parameters, drop duplicates,
   and call `verifier.verify()` on what's left. Only a row with a genuine
   passing `ScoreReceipt` survives.
4. **Write locally**: a tuning JSONL (`{"input", "output", "holdout": false,
   "synthetic": true}` per line) plus a manifest recording the plan id, the
   descriptor, and every receipt — only if at least one row survived step 3.

Any failure at any step — a 422 from the backend, a missing generator or
verifier, a digest mismatch, an expired plan, an unauthorized or malformed
response, the feature flag being off, or a generator that produced nothing a
verifier would accept — fails closed: `ColdStartOutcome.DISCOVERY_ONLY`,
`optimizer_eligible=False`, a typed `DiscoveryGap` on `result.gap`, and
**zero files written**.

| `result.gap.reason` | Where it comes from |
|---|---|
| `no_generator_supplied` / `no_verifier_supplied` | Client-side; caught before any network call |
| `invalid_verifier_kind` | Client-side; `verifier.kind` drifted off the enum after construction |
| `descriptor_arity_mismatch` | Client-side pre-flight, or the backend's own 422 |
| `no_local_scoring_authority` | Backend 422 — it read your declared `verifier.kind` and refused |
| `no_local_generation_capability` | Backend 422 — it read your declared `generation_capabilities` and refused |
| `descriptor_digest_mismatch` | The recomputed digest didn't match the plan's — never trust a mismatched plan |
| `plan_expired` | The plan's `expires_at` had already passed |
| `unauthorized` | Backend returned 401/403 |
| `feature_disabled` | Backend returned 501 — `ENABLE_COLD_START_GENERATION` is off on that deployment |
| `malformed_response` | The transport returned something that doesn't match the wire contract |
| `no_verified_candidates` | Generation ran, but no candidate earned a passing `ScoreReceipt` |

## A complete, runnable example

Pass your `@traigent.optimize`-decorated function directly. The SDK unwraps
the decorator itself (following `__wrapped__` or `.func`) before reading the
signature, so the descriptor describes your real function rather than the
wrapper's generic `(*args, **kwargs)`.

This example never calls a provider, an LLM, or a real backend — the
generator is a fixed local catalog, the verifier is a plain regex, and
`transport` is a stand-in you would replace with a real `POST`. It
demonstrates both outcomes, including reading `result.gap.reason`:

```python runnable
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import traigent
from traigent.generation.coldstart import (
    ColdStartOutcome,
    LocalVerifier,
    ScoreReceipt,
    build_cold_start_eval_set,
)
# TransportResponse is not part of this package's public six-name surface
# (see "What never leaves this six-name surface" below) — it is the one type
# a real transport must still return, so it has to come from the private
# module. Treat this import as load-bearing but not stable across releases.
from traigent.generation.coldstart._plan import TransportResponse


@traigent.optimize(
    objectives=["accuracy"],
    configuration_space={"strategy": ["first_amount", "last_amount"]},
    offline=True,
    # no eval_dataset yet -- that is exactly the gap this call fills
)
def extract_refund_amount(message: str) -> float:
    config = traigent.get_config()
    amounts = re.findall(r"\$([0-9]+(?:\.[0-9]{2})?)", message)
    if not amounts:
        return 0.0
    picked = amounts[0] if config.get("strategy") == "first_amount" else amounts[-1]
    return float(picked)


_TEMPLATES = (
    ("Please refund the ${amount:.2f} charge on order #4471.", 42.00),
    ("Customer was billed ${amount:.2f} in error last Tuesday.", 18.50),
    ("Reverse the duplicate ${amount:.2f} payment on invoice INV-9.", 105.00),
)


def propose_refund_examples(candidate_limit: int):
    """Deterministic generator: constructs a message around a known amount,
    then reports that amount as the candidate output (its own claim -- see
    the verifier below for the independent check that earns it a receipt)."""
    for template, amount in _TEMPLATES[:candidate_limit]:
        yield ({"message": template.format(amount=amount)}, amount)


class IndependentAmountCheck(LocalVerifier):
    """Re-extracts the dollar amount from the raw message with its OWN regex
    and only accepts the candidate if the two independently agree. A
    verifier that instead trusted the generator's output unchecked would
    have to report provenance='oracle_returned', never
    'independently_verified' -- that distinction is a closed vocabulary the
    SDK validates, not free text."""

    kind = "executable_property"

    def verify(self, *, inputs: Mapping[str, Any], output: Any) -> ScoreReceipt | None:
        message = inputs.get("message")
        if not isinstance(message, str) or not isinstance(output, (int, float)):
            return None
        found = re.findall(r"\$([0-9]+(?:\.[0-9]{2})?)", message)
        if not found:
            return None
        recomputed = float(found[0])
        passed = abs(recomputed - float(output)) < 0.001
        return ScoreReceipt(
            verifier_id="refund_amount.independent_regex.v1",
            verifier_kind=self.kind,
            passed=passed,
            provenance="independently_verified",
            evidence={"recomputed_amount": recomputed},
        )


def fake_backend_grants_plan(request):
    """Stand-in for the real POST to /api/v1/guidance/cold-start-plan. A real
    transport sends `request` over HTTP and wraps the JSON response in a
    TransportResponse -- swap this out for that; nothing about the
    generator/verifier above changes."""
    from traigent.generation.coldstart._contract import compute_descriptor_digest

    return TransportResponse(
        200,
        {
            "plan_id": "csp_demo",
            "protocol_version": "cold-start.v1",
            "descriptor_digest": compute_descriptor_digest(request["descriptor"]),
            "candidate_limit": request["budget"]["candidate_limit"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )


def fake_backend_declines(request):
    """Stand-in for a deployment that has not granted this verifier kind --
    fails closed, exactly like the real endpoint's 422."""
    return TransportResponse(
        422, {"error": "declined", "reason": "no_local_scoring_authority"}
    )


with tempfile.TemporaryDirectory() as tmp:
    output_dir = Path(tmp)

    built = build_cold_start_eval_set(
        extract_refund_amount,
        generator=propose_refund_examples,
        verifier=IndependentAmountCheck(),
        transport=fake_backend_grants_plan,
        output_dir=output_dir,
        generation_capabilities=("deterministic_contract",),
        requested_candidate_limit=3,
    )
    if built.outcome is ColdStartOutcome.EVAL_SET_BUILT:
        print(f"wrote {built.row_count} rows to {built.eval_set_path}")
        print(f"manifest: {built.manifest_path}")
    else:
        print(f"no eval set: {built.gap.reason} -- {built.gap.detail}")

    declined = build_cold_start_eval_set(
        extract_refund_amount,
        generator=propose_refund_examples,
        verifier=IndependentAmountCheck(),
        transport=fake_backend_declines,
        output_dir=output_dir,
        generation_capabilities=("deterministic_contract",),
    )
    if declined.outcome is ColdStartOutcome.DISCOVERY_ONLY:
        # Reading the gap is the point: an agent or a human decides what to
        # do next from `reason`/`detail`, never by guessing.
        print(f"no eval set: {declined.gap.reason} -- {declined.gap.detail}")
    else:
        print(f"wrote {declined.row_count} rows to {declined.eval_set_path}")
```

Running this prints:

```
wrote 3 rows to <tmp>/cold_start.jsonl
manifest: <tmp>/cold_start.manifest.json
no eval set: no_local_scoring_authority -- declined
```

The two calls share the same `func`, `generator`, and `verifier` — only
`transport` differs — to make one point concrete: supplying a real generator
and a real verifier does not guarantee `EVAL_SET_BUILT`. The backend still
has the final word on whether your declared `verifier.kind` and
`generation_capabilities` are acceptable for that deployment, and a decline
there is exactly as fail-closed as a missing generator.

## Parameters worth knowing about

| Parameter | Default | Notes |
|---|---|---|
| `dataset_name` | `"cold_start"` | Base filename (sanitized) for the JSONL + manifest pair |
| `requested_candidate_limit` | `12` | An ask, 1–1000; the backend's grant may be lower and always wins |
| `generation_capabilities` | **required** | Non-empty, from `{"deterministic_contract", "customer_llm"}`. Deliberately has NO default: a default would let you tell the backend an LLM was involved when your generator never called one. State what your generator actually does — `deterministic_contract` for a fixed rule or template, `customer_llm` when it calls your own model. |
| `containment_root` | `None` | Optional root `output_dir` must stay under |
| `clock` | real UTC now | Injectable for testing plan-expiry handling |

`verifier.kind` (not a `build_cold_start_eval_set` parameter — it's a class
attribute your `LocalVerifier` subclass declares) must be one of
`deterministic_reference`, `executable_property`, `state_transition`,
`human_review`, `calibrated_judge`. There is no way to pass `verifier_kinds`
directly to `build_cold_start_eval_set` — it is always derived from the
`verifier` object you supplied, never a free-form claim made separately.

## What never leaves this six-name surface

The public surface is exactly six names —
`ColdStartOutcome`, `ColdStartResult`, `DiscoveryGap`, `LocalVerifier`,
`ScoreReceipt`, `build_cold_start_eval_set` — and stays that way by design;
generation technique, a default generator, a default verifier, a bundled
HTTP client, or built-in model/API-key handling would all be scope creep
this module deliberately refuses to carry. Everything it writes locally
(`ScoreReceipt.provenance`, the manifest, the tuning JSONL) uses closed,
validated vocabularies rather than free text — a `provenance` value outside
`oracle_returned` / `independently_verified` is not admissible evidence and
the row carrying it is dropped, the same as an unrecognized `verifier.kind`.

## Holdout discipline

Every row this path writes carries `"holdout": false, "synthetic": true` —
set by the executor itself, not something a generator or verifier can
override. Treat that as load-bearing, matching the rest of this skill:

- Cold-start rows are tuning-only. Never relabel one as holdout.
- Do not use the generator's technique, the verifier's own examples, or a
  cold-start tuning run's failures to construct the claim set.
- Build the real holdout later from genuine traffic or independently
  reviewed evidence, split by a stable leakage boundary (customer, document,
  repository, time window).
- Report tuning-slice movement and untouched-holdout movement separately.
  With no holdout yet, say so plainly and report only that the result
  supports configuration search — not a generalization claim.
