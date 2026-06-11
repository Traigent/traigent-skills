---
name: traigent-composite-knobs
description: "Declare and run Traigent composite knobs: cascades, routers, ensembles, self-consistency, best-of-n, self-refine, self-debug, ReAct tool loops, verification gates, mixture-of-experts, and fallback patterns. Use when choosing a catalog pattern, wiring StageRunner/LoopBodyRunner execution, merging composite telemetry into metrics, or explaining calibration-backed claim scope."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.1"
---

# Traigent Composite Knobs

## When to Use

Requires `traigent>=0.13.0.dev1`.

Use this skill when:

- Choosing a composite pattern from `traigent.knobs.patterns`
- Declaring cascades, routers, ensembles, loops, ReAct-style tool steps, verifier loops, mixture-of-experts, or fallback shapes
- Wiring `execute_composite` with `StageRunner` or `LoopBodyRunner`
- Returning `(output, metrics)` from an optimized function so composite telemetry rides the measures channel
- Explaining which values are tuned, calibrated, fixed, or observed

For exact factory signatures and per-pattern caveats, read `references/pattern-catalog.md`. For adaptive RAG and bounded refine specializations, read `references/advanced-recipes.md`.

## Quick Start

The canonical wiring is:

1. Declare a pattern factory such as `binary_cascade`, `router`, `self_refine`, or `moe`.
2. Spread the composite's `.members` into the surrounding configuration space when it supplies member `Knob` declarations.
3. Wire every referenced stage with `StageRunner` for sampling/voting positions or `LoopBodyRunner` for loop bodies.
4. Inside the decorated function, call `execute_composite` with the pattern's `.structure`, current tuned config, live calibrated CVAR values, and any `signals` or `predicates`.
5. Build ordinary numeric metrics, call `merge_composite_measures(metrics, run)`, and return exactly `(output, metrics)`.

Use this hybrid/cloud return shape from `composite_telemetry.py`:

```python
import traigent
from traigent.knobs.patterns import binary_cascade
from traigent.knobs.runtime import StageRunner, execute_composite
from traigent.knobs.telemetry import merge_composite_measures

GATE = "router_margin_threshold"
_EXPECTED = "STRONG"

COMPOSITE = binary_cascade(
    "answerer",
    base_stage="cheap",
    expert_stage="strong",
    threshold=GATE,
)


def _stage(outputs: list[str]) -> StageRunner:
    return StageRunner(
        run=lambda _item: list(outputs),
        key_fn=lambda x: x,
        samples=len(outputs),
    )

@traigent.optimize(
    eval_dataset=...,
    objectives=["accuracy"],
    configuration_space={"variant": ["cheap", "strong"]},
    default_config={"variant": "cheap"},
    execution_mode="hybrid",
)
def answer(text: str) -> tuple[str, dict[str, float]]:
    cfg = traigent.get_config()
    params = dict(cfg)
    run = execute_composite(
        COMPOSITE.structure,
        {"cheap": _stage([...]), "strong": _stage([_EXPECTED])},
        config=params,
        calibrated_values={GATE: params[GATE]},
    )
    # The composite_* keys become per-trial measures on the wire.
    metrics = {"accuracy": 1.0 if str(run.output) == _EXPECTED else 0.0}
    merge_composite_measures(metrics, run)
    return str(run.output), metrics
```

The evaluator recognizes exactly a two-item tuple `(output, metrics)` where `metrics` is numeric and identifier-keyed. Other return shapes are not unpacked.

With the tuple return, use the BUILT-IN evaluator (expected outputs in
`eval_dataset`, no custom `scoring_function`): a custom `scoring_function` or
3-arg `metric_functions` is currently NOT invoked with the unpacked prediction
on this path, and every trial silently scores `accuracy=0.0` (known SDK
issue). Uniform zero accuracy next to a sane built-in `score` means scoring
wiring, not a bad agent.

## WHEN-TO-USE DECISION TABLE

| Pattern | Agent shape it fits | What it tunes | Key CVARs |
|---|---|---|---|
| `binary_cascade` | Cheap base arm escalates to one expert arm on low vote margin. | Arm-level tuned params via `base_tuned_params` and `expert_tuned_params`; any `.members`. | One margin `threshold`. |
| `n_cascade` | Ordered escalation across three or more stages. | Per-stage `tuned_params`; any `.members`. | One margin threshold per non-terminal stage. |
| `self_consistency` | Sample one stage `k` times and majority-vote. | `stage_tuned_params`; `cardinality` if resolved from config; any `.members`. | Optional `accept_threshold`; `cardinality` if calibrated. |
| `best_of_n` | Sample one stage `k` times and choose with a judge. | Generator and judge tuned params; `cardinality` if resolved from config; any `.members`. | `cardinality` if calibrated. |
| `self_debug` | Retry a stage until an external predicate passes. | `stage_tuned_params`; state shape; any `.members`. | None required; predicate is runtime code. |
| `self_refine` | Refine threaded state until a calibrated signal accepts. | `stage_tuned_params`; state and signal input shape; any `.members`. | One signal `threshold`. |
| `react_tool_loop` | ReAct-style one-tool-step-per-iteration loop. | Planner/tool/failure-handler tuned params; any `.members`. | `tool_confidence_min`. |
| `verification_gate` | Generate, verify, revise loop with verifier pass score. | Verifier style, question count, model, context, revision policy; any `.members`. | `verifier_pass_threshold`. |
| `moe` | Committee of distinct experts, aggregated by vote or judge. | Per-expert tuned params and optional judge params; any `.members`. | Optional vote `accept_threshold`. |
| `router` | Pre-dispatch to exactly one arm using left-to-right adequacy signals. | Per-arm `tuned_params`; signal input declarations; any `.members`. | One threshold per signal gate. |
| `fallback` | Ordered post-cascade fallback on `no_accept` or low margin. | Per-arm `tuned_params`; any `.members`. | One margin threshold per non-terminal arm. |

## Members and the Configuration Space

A factory returns a `CompositeKnob` declaration bundle: `.structure` is the IR root, `.members` are ordinary member `Knob` declarations, `.provenance` records the pattern name plus a canonical param hash, and `.telemetry_names` lists standard measure names.

Spread `.members` into the surrounding configuration space. Do not treat the composite as binding values. Member bindings remain `Tuned`, `Calibrated`, or `Fixed`; the composite only references names and declares control flow. CVARs such as thresholds must be calibrated and passed at execution time through `calibrated_values`.

The vocabulary, in one line: **TVARs are searched, CVARs are calibrated,
policies govern control flow, KPIs/objectives score outcomes.** For
domain-specific structural knob vocabularies (text2SQL, RAG/multi-hop QA),
cross-reference `traigent-structural-spine` — this skill extends it with
composite control flow; it does not replace it.

## Telemetry

Composite telemetry is content-free and starts in `run.measures`.

| Kind | Standard names |
|---|---|
| Post-cascade (`binary_cascade`, `n_cascade`, `fallback`) | `escalation_rate`, `stage_selected`, `gate_margin_pass_rate` |
| Router/pre-cascade | `route_selected`, `dispatch_signal_margin`, `gate_signal_adequate` |
| Ensemble (`self_consistency`, `best_of_n`, `moe`) | `vote_agreement`, `vote_margin`, `candidates_evaluated`, `candidates_excluded` |
| Loop (`self_debug`, `self_refine`, `react_tool_loop`, `verification_gate`) | `iterations_used`, `stop_reason` |

Use `merge_composite_measures(metrics, run, prefix="composite")` to flatten finite numeric telemetry into the existing measures channel. Structured maps are flattened by gate index. Non-numeric enum values such as `stop_reason` remain observable on `run.measures` but are not copied to numeric measures.

**Wire boundary (deliberate)**: composite structure, members, and provenance
are SDK-local metadata — nothing about a composite crosses the backend wire
except these numeric `composite_*` measures riding the EXISTING measures
channel. Do not invent new request/response fields for composites; a future
composite wire summary is a Schema-first change (TraigentSchema), not an SDK
patch.

## Claim Scope

Composite end-to-end metrics are OBSERVATIONS from the evaluated trials. Per-variable calibration certificates are the only procedural claims. Winner-level product copy should say `Calibration-backed winner (client-attested)`. Do not use a bare `Certified` winner label, and do not promise future behavior from a composite run.
