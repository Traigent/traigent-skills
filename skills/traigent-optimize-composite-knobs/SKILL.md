---
name: traigent-optimize-composite-knobs
description: "Declare and run Traigent composite knobs: cascades, routers, ensembles, self-consistency, best-of-n, self-refine, self-debug, ReAct tool loops, verification gates, mixture-of-experts, and fallback patterns. Use when choosing a catalog pattern, wiring StageRunner/LoopBodyRunner execution, merging composite telemetry into metrics, or explaining calibration-backed claim scope."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0.6"
---

# Traigent Composite Knobs

## When to Use

Requires `traigent>=0.13.0` (the knobs API is present on all current SDK releases).

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
2. If the factory was called with an explicit `members=` dict, spread those `Knob` declarations into the surrounding configuration space. Most patterns (including `binary_cascade` with no `members=` argument) return an empty `.members` dict — spreading it is a no-op. Threshold CVARs like the cascade gate must be declared explicitly in `configuration_space` as tuned variables (or passed as literals in `calibrated_values`); they are NOT auto-populated from `.members`.
3. Wire every referenced stage with `StageRunner` for sampling/voting positions or `LoopBodyRunner` for loop bodies.
4. Inside the decorated function, call `execute_composite` with the pattern's `.structure`, current tuned config, live calibrated CVAR values, and any `signals` or `predicates`.
5. Build ordinary numeric metrics, call `merge_composite_measures(metrics, run)`, and return exactly `(output, metrics)`.

Use this portal-compatible return shape from `composite_telemetry.py`:

```python
from pathlib import Path

import traigent
from traigent.knobs.patterns import binary_cascade
from traigent.knobs.runtime import StageRunner, execute_composite
from traigent.knobs.telemetry import merge_composite_measures

GATE = "router_margin_threshold"

# On the tuple-return path the function scores itself (see the note below),
# so it needs the expected answer in scope. _EXPECTED stands in for your
# dataset's expected_output; in real code look it up per example.
_EXPECTED = "STRONG"

# Tiny self-contained dataset so this block runs as-is.
Path("eval").mkdir(exist_ok=True)
Path("eval/composite_demo.jsonl").write_text(
    '{"input": {"text": "route me"}, "expected_output": "STRONG"}\n'
)

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
    eval_dataset="eval/composite_demo.jsonl",
    objectives=["accuracy"],
    configuration_space={
        "variant": ["cheap", "strong"],
        # Declare the threshold as a tuned variable so params[GATE] resolves.
        # The optimizer searches discrete margin values; the winning value
        # doubles as the live calibrated_value passed to execute_composite.
        GATE: [0.3, 0.5, 0.7],
    },
    default_config={"variant": "cheap", GATE: 0.5},
)
def answer(text: str) -> tuple[str, dict[str, float]]:
    cfg = traigent.get_config()
    params = dict(cfg)
    run = execute_composite(
        COMPOSITE.structure,
        {"cheap": _stage(["weak-guess"]), "strong": _stage([_EXPECTED])},
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
issue). Diagnostic tell, by SDK version: on <= 0.21.3, uniform zero accuracy
next to a sane built-in `score` means scoring wiring, not a bad agent; `score`
mirrors the primary objective on SDKs after 0.21.3
(see version-matrix: `score-relocation`), so it is also 0.0 here and the sane built-in value is
relocated to `exact_match_default` — check that key instead, and look for the
run-level "custom scoring_function defines the 'accuracy' objective" log line.
**Escape hatch:** if you need custom scoring on this
path, compute the metric inside the function and return it in the tuple's
metrics dict (as the Quick Start's `accuracy` does) — do not wire a
`scoring_function` and wonder why it never fires. If neither works for your
case, stop and surface the SDK limitation to the user rather than iterating.

Before any paid run, assert the gate CVAR is actually resolvable — an
undeclared threshold is a per-trial `KeyError` after money is spent:

```python
# contract: skip
assert GATE in answer.configuration_space or GATE in calibrated_values
```

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

The table above keys off agent **shape**. Before wiring a knob, also check the **failure mode** it fixes — shape tells you which pattern is expressible, failure mode tells you whether it helps:

- **repair** → erroring/malformed outputs
- **self-consistency / best-of-n** → output instability
- **retrieval / similar-fewshot** → unseen patterns / missing examples
- **chain-of-thought / plan** → multi-step reasoning

Here, repair = `self_debug`/`self_refine` in the table above; retrieval, similar-fewshot, chain-of-thought, and plan are structural knobs (`retriever`, `fewshot_selector`, `prompting_strategy`, `generation_path`) — see `traigent-optimize-config-space` and its `references/structural-spine.md`.

A knob wired in blind adds cost and can lower the score.

**⚠️ Stochastic knobs vs. exact-match metrics**: `temperature>0` and self-consistency trade determinism for exploration; on a frail exact-match/case-sensitive scorer they can turn a correct deterministic answer wrong. Pin `temperature=0` there — provider APIs default to a nonzero temperature (typically `1.0`) when it is unset, so unset ≠ deterministic — and open it up only when the scorer tolerates surface variation (a validated semantic/execution-match equivalence class).

## Members and the Configuration Space

A factory returns a `CompositeKnob` declaration bundle: `.structure` is the IR root, `.members` are ordinary member `Knob` declarations, `.provenance` records the pattern name plus a canonical param hash, and `.telemetry_names` lists standard measure names.

Spread `.members` into the surrounding configuration space **only when the factory was called with a non-empty `members=` argument**. Factories called without `members=` (or with `members=None`) return `.members = {}` — spreading it is a no-op and will NOT populate threshold keys into `configuration_space`. Threshold CVARs (e.g. `router_margin_threshold` for `binary_cascade`) are not auto-populated by `.members`; they must be declared explicitly in `configuration_space` (to tune them) or supplied as literals in `calibrated_values` (to fix them). Omitting them from both causes `params[GATE]` to raise `KeyError` on every trial. Member bindings that ARE present remain `Tuned`, `Calibrated`, or `Fixed`; the composite only references names and declares control flow.

The vocabulary, in one line: **TVARs are searched, CVARs are calibrated,
policies govern control flow, KPIs/objectives score outcomes.** For
domain-specific structural knob vocabularies (text2SQL, RAG/multi-hop QA),
cross-reference `traigent-optimize-config-space` and
`traigent-optimize-config-space/references/structural-spine.md` -- this skill
extends that structural vocabulary with composite control flow; it does not
replace it.

## Telemetry

<!-- PROTECTED -->
Composite telemetry is content-free and starts in `run.measures`.
<!-- /PROTECTED -->

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

<!-- PROTECTED -->
## Claim Scope

Composite end-to-end metrics are OBSERVATIONS from the evaluated trials. Per-variable calibration certificates are the only procedural claims. Winner-level product copy should say `Calibration-backed winner (client-attested)`. Do not use a bare `Certified` winner label, and do not promise future behavior from a composite run.
<!-- /PROTECTED -->

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
