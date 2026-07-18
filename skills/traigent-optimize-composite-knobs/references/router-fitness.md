# Router and cascade fitness

Use this check before adding conditional model dispatch. A routed system adds signal, sampling,
calibration, and latency costs; it is useful only when those costs buy a predictable decision.

## First classify the timing

The current composite catalog separates two mechanisms that older guidance both called a router:

| Decision timing | Current pattern | Evidence available to the gate |
|---|---|---|
| Before any arm runs | `router` | caller-provided input/metadata adequacy signals |
| After a cheap arm produces vote-bearing outputs | `binary_cascade` or `n_cascade` | output vote margin |

Do not implement cheap-model self-consistency escalation with `router`: its gates run before any arm.
Use a post-output cascade. Conversely, do not pay for cheap samples when a reliable pre-dispatch
signal already exists.

## Fitness gate

Proceed only when all applicable checks pass:

1. **The gate signal is defined.** A pre-dispatch router needs a caller-owned numeric signal with
   declared inputs. A vote-margin cascade needs a meaningful `key_fn(output) -> hashable` on its
   base `StageRunner`. Raw equality is rarely suitable for free-form text.
2. **The signal predicts the decision.** On a held-out slice, higher adequacy or margin must separate
   cases where the early arm is sufficient from cases where escalation helps. Treat AUC near 0.5 as
   random; the historical prototype used roughly 0.55 only as a screening heuristic, not a product
   guarantee.
3. **There is headroom.** The later/stronger arm must outperform the early/cheap arm on the intended
   metric. If it does not, routing can only add cost.
4. **The full economics work.** Include every base sample, the escalation rate, the expert call,
   evaluator cost, and latency. For a K-sample base and escalation fraction `p`, reason about
   `K * base_cost + p * expert_cost`, not merely `p * expert_cost`.
5. **The metric can judge the trade-off.** Use execution equivalence, normalized labels, canonical
   structured output, or another task-valid comparator. If equivalence is unresolved, fix the
   evaluator before optimizing the route.

If any check fails, keep the simpler control or use a different signal such as provider log
probability, a deterministic validator, or a semantic comparator whose own reliability is audited.

## Comparator examples for vote-bearing cascades

```python
# Classification
key_fn = lambda label: label.strip().lower()

# Structured output
key_fn = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))

# SQL when execution equivalence is the product criterion
key_fn = lambda sql: result_key(execute_read_only(sql, fixture_db))
```

The comparator is product semantics, not plumbing. Audit collisions and false splits on a labeled
slice. A comparator that maps everything to one key reports false confidence; one that maps every
sample to a unique key reports permanent uncertainty.

## Calibrate; do not guess

Declare every threshold as a CVAR and supply it through `calibrated_values` or the surrounding
configuration space as documented in the pattern catalog. Select the threshold on evaluation data
against a precommitted quality/cost rule, then confirm it on a held-out slice.

Production routing is gold-free: it uses the frozen threshold and live signal only. Gold labels are
for fitness assessment and calibration, not runtime dispatch.

Measure at least:

- quality versus all-early, all-late, and a cost-matched random-escalation control;
- escalation/route-selection rate and the signal distribution;
- total calls, cost, and latency including K-sample overhead;
- error or abstention rate by selected arm;
- calibration drift on later data.

## Historical provenance and claim boundary

The retired router prototype reported two different external
`guided_generation_spider` fixtures:

- a +2.8-point advantage over random escalation at a 20% expert budget across 12 schemas;
- a separate self-check fixture recovering +3.2 points at a 20% budget.

Those figures motivate the fitness checks; they are not current SDK guarantees and must not be
presented as evidence for a new user's task. Reproduce the comparison on the user's own evaluator
before making a routing claim.

## Limitations

- Vote margin requires multiple base calls on every request and increases tail latency.
- Pre-dispatch signals can encode proxy bias or leak task-specific assumptions.
- Routing cannot exceed the best available arm on cases where that arm itself fails.
- Threshold calibration can drift as models, prompts, and traffic change.
- The current `fallback` pattern is not exception-triggered; provider errors remain absorbing
  unless host code or a suitable loop handles them.
