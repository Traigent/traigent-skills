# Composite Pattern Catalog

This reference mirrors `traigent.knobs.patterns`, `traigent.knobs.runtime`, and `traigent.knobs.telemetry`. Factories return declarations only: `.structure`, `.members`, `.provenance`, and `.telemetry_names`.

## Runtime Surface

```python
@dataclass(frozen=True, slots=True)
class StageRunner:
    run: Callable[[Any], Sequence[Any]]
    key_fn: Callable[[Any], VoteKey] | None = None
    samples: int = 1
```

```python
def execute_composite(
    knob: CompositeNode,
    stages: Mapping[str, StageEntry],
    *,
    config: Mapping[str, Any],
    calibrated_values: Mapping[str, float | int],
    signals: Mapping[str, Callable[..., Any]] | None = None,
    predicates: Mapping[str, Callable[..., Any]] | None = None,
    registry: Mapping[str, CompositeNode] | None = None,
) -> CompositeRunResult:
```

```python
def merge_composite_measures(
    metrics: dict[str, float | int],
    run: CompositeRunResult,
    *,
    prefix: str = "composite",
) -> dict[str, float | int]:
```

## `binary_cascade`

```python
def binary_cascade(
    name: str,
    *,
    base_stage: str,
    expert_stage: str,
    threshold: str,
    base_tuned_params: tuple[str, ...] = (),
    expert_tuned_params: tuple[str, ...] = (),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Cascade(arms=[stage(base), stage(expert)], gates=[margin_below theta], post)`.
- Calibration recipe: calibrate `threshold` as a margin CVAR before execution; pass it in `calibrated_values`.
- Telemetry: `escalation_rate`, `stage_selected`, `gate_margin_pass_rate`.
- Limitations: exactly two arms; the base arm must be vote-bearing when it feeds the margin gate.

## `n_cascade`

```python
def n_cascade(
    name: str,
    *,
    stages: tuple[str, ...],
    thresholds: tuple[str, ...],
    tuned_params: tuple[tuple[str, ...], ...] | None = None,
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Cascade(arms=[stage(a_1)..stage(a_m)], gates=[theta_1..theta_{m-1}], post)`.
- Calibration recipe: calibrate each threshold CVAR; `len(thresholds)` must match `len(stages) - 1`.
- Telemetry: `escalation_rate`, `stage_selected`, `gate_margin_pass_rate`.
- Limitations: `tuned_params`, when provided, must declare exactly one tuple per stage.

## `self_consistency`

```python
def self_consistency(
    name: str,
    *,
    stage: str,
    cardinality: str,
    accept_threshold: str | None = None,
    stage_tuned_params: tuple[str, ...] = (),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Ensemble(arms=[stage(a)], cardinality=k, majority_vote, accept?)`.
- Calibration recipe: resolve `cardinality` from tuned config or `calibrated_values`; calibrate optional `accept_threshold` when present.
- Telemetry: `vote_agreement`, `vote_margin`, `candidates_evaluated`, `candidates_excluded`.
- Limitations: single generator stage; optional accept gate is `vote_margin >= threshold`.

## `best_of_n`

```python
def best_of_n(
    name: str,
    *,
    stage: str,
    judge_stage: str,
    cardinality: str,
    stage_tuned_params: tuple[str, ...] = (),
    judge_tuned_params: tuple[str, ...] = (),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Ensemble(arms=[stage(a)], cardinality=k, judge_max(stage(judge)))`.
- Calibration recipe: resolve `cardinality` from tuned config or `calibrated_values`; no threshold CVAR is implied.
- Telemetry: `vote_agreement`, `vote_margin`, `candidates_evaluated`, `candidates_excluded`.
- Limitations: judge output must be a finite numeric score at runtime.

## `self_debug`

```python
def self_debug(
    name: str,
    *,
    stage: str,
    predicate: str,
    max_iters: int,
    state_keys: tuple[str, ...] = ("attempt", "critique"),
    stage_tuned_params: tuple[str, ...] = (),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Loop(body=stage(a), state_keys, stop=external_accept(tests), max_iters=K)`.
- Calibration recipe: no built-in CVAR; provide the named predicate in `predicates`.
- Telemetry: `iterations_used`, `stop_reason`.
- Limitations: `external_accept` is opaque runtime code; this loop is not unroll-eligible. `max_iters` is a literal int, not a tuned variable.

## `self_refine`

```python
def self_refine(
    name: str,
    *,
    stage: str,
    signal: str,
    threshold: str,
    max_iters: int,
    state_keys: tuple[str, ...] = ("draft",),
    signal_inputs: tuple[str, ...] = (),
    stage_tuned_params: tuple[str, ...] = (),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Loop(body=stage(a), state_keys, stop=signal_accept(sigma, theta), max_iters=K)`.
- Calibration recipe: calibrate `threshold`; provide `signal` in `signals`; keep `signal_inputs` within `state_keys`.
- Telemetry: `iterations_used`, `stop_reason`.
- Limitations: only one acceptance-direction signal threshold; `max_iters` is literal. This is the loop family that can be unrolled to a K-chain.

## `react_tool_loop`

```python
def react_tool_loop(
    name: str,
    *,
    stage: str,
    signal: str,
    tool_confidence_min: str,
    max_tool_calls: int,
    state_keys: tuple[str, ...] = (
        "scratchpad",
        "tool_calls",
        "observations",
        "confidence",
        "last_error",
    ),
    signal_inputs: tuple[str, ...] = (
        "scratchpad",
        "tool_calls",
        "observations",
        "confidence",
        "last_error",
    ),
    stage_tuned_params: tuple[str, ...] = (
        "planner_style",
        "tool_allowlist",
        "observation_format",
        "failure_handler",
    ),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Loop(body=stage(a), state_keys, stop=signal_accept(tool_confidence, theta), max_iters=K)`.
- Calibration recipe: calibrate `tool_confidence_min`; provide `signal` in `signals`.
- Telemetry: `iterations_used`, `stop_reason`.
- Limitations: `max_tool_calls` maps to literal `max_iters` and assumes at most one tool step per body call. `tool_cost_cap` is not enforced by this pattern or the current algebra.

## `verification_gate`

```python
def verification_gate(
    name: str,
    *,
    stage: str,
    verifier_signal: str,
    verifier_pass_threshold: str,
    verification_style: str,
    verification_question_count: str,
    verifier_model: str,
    independent_context: str,
    revision_policy: str,
    max_iters: int = 2,
    state_keys: tuple[str, ...] = (
        "draft",
        "verification_questions",
        "verification_answers",
        "verifier_pass_score",
        "contradiction_score",
        "revision",
        "independent_context",
    ),
    signal_inputs: tuple[str, ...] = (
        "draft",
        "verification_answers",
        "independent_context",
    ),
    contradiction_score_max: str | None = None,
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: verifier loop with `signal_accept(verifier_signal, verifier_pass_threshold)`.
- Calibration recipe: calibrate `verifier_pass_threshold`; provide `verifier_signal` in `signals`. Treat `verification_style`, `verification_question_count`, `verifier_model`, `independent_context`, and `revision_policy` as stage tuned-param refs.
- Telemetry: `iterations_used`, `stop_reason`.
- Limitations: single-threshold loop only. Passing `contradiction_score_max` raises; simultaneous contradiction and pass thresholds require a future compound stop. `max_iters` is literal, not tunable.

## `moe`

```python
def moe(
    name: str,
    *,
    experts: tuple[str, ...],
    aggregate: str = "vote",
    judge_stage: str | None = None,
    accept_threshold: str | None = None,
    expert_tuned_params: tuple[tuple[str, ...], ...] | None = None,
    judge_tuned_params: tuple[str, ...] = (),
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Ensemble(arms=[stage(expert_1)..stage(expert_m)], aggregate, committee)`.
- Calibration recipe: for `aggregate="vote"`, calibrate optional `accept_threshold`; for `aggregate="judge"`, provide `judge_stage` and no accept threshold.
- Telemetry: `vote_agreement`, `vote_margin`, `candidates_evaluated`, `candidates_excluded`.
- Limitations: at least two distinct expert stages. `aggregate="vote"` forbids `judge_stage`; `aggregate="judge"` requires it and forbids `accept_threshold`.

## `router`

```python
def router(
    name: str,
    *,
    arms: tuple[str, ...],
    signals: tuple[str, ...],
    thresholds: tuple[str, ...],
    tuned_params: tuple[tuple[str, ...], ...] | None = None,
    signal_inputs: tuple[tuple[str, ...], ...] | None = None,
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Cascade(arms=[stage(a_i)], gates=[signal_below sigma_i theta_i], pre)`.
- Calibration recipe: calibrate each threshold CVAR; provide each signal in `signals`; declare signal input coverage with `signal_inputs`.
- Telemetry: `route_selected`, `dispatch_signal_margin`, `gate_signal_adequate`.
- Limitations: dispatch evaluates gates left-to-right before any arm runs. `signals` and `thresholds` must have equal length; terminal arm is ungated.

## `fallback`

```python
def fallback(
    name: str,
    *,
    arms: tuple[str, ...],
    thresholds: tuple[str, ...],
    tuned_params: tuple[tuple[str, ...], ...] | None = None,
    members: dict[str, Knob[Any]] | None = None,
) -> CompositeKnob:
```

- IR shape: `Cascade(arms=[stage(a_i)], gates=[margin_below theta_i], post)`.
- Calibration recipe: calibrate each margin threshold CVAR; use nested no-accept-capable composites or real margin thresholds for non-terminal fallback behavior.
- Telemetry: `escalation_rate`, `stage_selected`, `gate_margin_pass_rate`.
- Limitations: fallback is `no_accept`-triggered or low-margin-triggered, not error-triggered. Leaf arms cannot signal failure; errors remain absorbing. With a `theta=0.0` convention, leaf arms never escalate.
