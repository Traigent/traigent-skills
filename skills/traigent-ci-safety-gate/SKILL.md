---
name: traigent-ci-safety-gate
description: "Add Traigent safety and promotion gates to CI. Use when users ask to add safety constraints, gate the optimized config, prevent regressions in CI, enforce cost or latency budgets, compare candidate versus incumbent, validate TVL specs, or write GitHub Actions for agent optimization safety."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0"
---

# CI Safety Gate

## When to Use

Use this skill when the user asks:

- "add safety constraints"
- "gate the optimized config"
- "prevent regressions in CI"
- "cost/latency budget"
- "GitHub Actions for my agent"

<!-- PROTECTED -->
The gate should fail closed: missing metrics, NaN metrics, parse failures, rejected promotion decisions, and budget breaches should stop promotion.
<!-- /PROTECTED -->

## In-Run Safety Constraints

Use `safety_constraints=[...]` on `@traigent.optimize` to filter unsafe trial results during optimization. `SafetyConstraint` and `CompoundSafetyConstraint` are callable as `constraint(config, metrics) -> bool`; a failed threshold returns `False`. NaN scores fail closed, and missing metric keys should use a failing default.

```python
import litellm
import traigent
from traigent.api.safety import (
    CallableMetric,
    CompoundSafetyConstraint,
    MetricKeyMetric,
    SafetyConstraint,
    SafetyThreshold,
)

def prompt_model(prompt: str, *, model: str) -> str:
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""

quality_gate = SafetyConstraint(
    metric=MetricKeyMetric(
        name="quality_score",
        metric_key="quality_score",
        default=0.0,
    ),
    threshold=SafetyThreshold(
        metric_name="quality_score",
        operator=">=",
        value=0.85,
    ),
)

def latency_within_budget(config, metrics):
    latency_ms = metrics.get("latency_ms")
    return 1.0 if isinstance(latency_ms, (int, float)) and latency_ms <= 1200 else 0.0

latency_gate = SafetyConstraint(
    metric=CallableMetric(
        name="latency_budget",
        evaluator=latency_within_budget,
    ),
    threshold=SafetyThreshold(
        metric_name="latency_budget",
        operator=">=",
        value=1.0,
    ),
)

hard_gate = CompoundSafetyConstraint(
    constraints=[quality_gate, latency_gate],
    combinator="and",
)

@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
    objectives=["quality_score"],
    safety_constraints=[hard_gate],
)
def answer(question: str) -> str:
    config = traigent.get_config()
    return prompt_model(question, model=config["model"])
```

Keep safety metrics simple, explicit, and reviewable. Complex semantic safety should still have a deterministic shell: schema validity, refusal policy, citation checks, cost caps, and latency caps.

## Promotion Gate

Use `PromotionGate` to compare a candidate config against the incumbent on the same holdout. `evaluate` returns a decision with `decision` equal to `promote`, `reject`, or `no_decision`.

```python
from traigent.tvl.models import PromotionPolicy
from traigent.tvl.promotion_gate import ObjectiveSpec, PromotionGate

policy = PromotionPolicy(
    dominance="epsilon_pareto",
    alpha=0.05,
    min_effect={"accuracy": 0.01, "latency_ms": 25.0},
    adjust="BH",
)
objectives = [
    ObjectiveSpec(name="accuracy", direction="maximize"),
    ObjectiveSpec(name="latency_ms", direction="minimize"),
]

gate = PromotionGate(policy=policy, objectives=objectives)
decision = gate.evaluate(
    incumbent_metrics={"accuracy": [0.81, 0.82, 0.80], "latency_ms": [880, 900, 870]},
    candidate_metrics={"accuracy": [0.84, 0.85, 0.83], "latency_ms": [910, 905, 920]},
)
print(decision.decision, decision.reason)
```

A statistical gate can tell you whether the candidate has enough evidence to promote, reject, or remain undecided on the measured evaluation dataset. It cannot prove universal safety, discover unmeasured regressions, or rescue a biased evaluator.

Validate TVL specs in CI before running the gate:

```bash
python -m traigent.tvl path/to/promotion-gate.tvl --strict
```

## The Two CI Checks

SAFETY: run a holdout regression check against a pinned baseline config.

- Pull request job: run offline/mock under `TRAIGENT_OFFLINE_MODE=true` to verify wiring, script shape, and fail-closed behavior without spending.
- Scheduled job: run the real holdout evaluation under `TRAIGENT_RUN_COST_LIMIT` with account credentials and compare candidate vs incumbent.

EFFICIENCY: assert `results.total_cost` and latency metrics remain within budget. Fail the job on cost breach, latency breach, rejected promotion, missing metrics, parse failures, or safety regression.

Minimal GitHub Actions shape:

```yaml
name: Traigent safety gate

on:
  pull_request:

jobs:
  # PR job: offline wiring check only — static env, zero spend. The paid
  # nightly job is a separate job with its own static env; see
  # references/gate-workflow.md for the full two-job workflow.
  safety-gate:
    runs-on: ubuntu-latest
    env:
      TRAIGENT_RUN_COST_LIMIT: "0.00"
      TRAIGENT_OFFLINE_MODE: "true"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python -m traigent.tvl tvl/ --strict
      - run: python scripts/run_holdout_eval.py --config configs/baseline.json --output .gate/incumbent.json
      - run: python scripts/run_holdout_eval.py --config configs/candidate.json --output .gate/candidate.json
      - run: python scripts/traigent_gate.py --incumbent .gate/incumbent.json --candidate .gate/candidate.json --max-cost 0.01 --max-latency-ms 1200
```

For a full copy-paste workflow and gate script, read `references/gate-workflow.md`.

Planned: a `traigent ci` command group will package these checks; the manual recipe stays valid.

## Claim Scope

Gate decisions are statistical decisions on the measured evaluation dataset and configured objectives, not broad safety claims. Re-run the gate when the evaluation dataset, evaluator, baseline config, candidate config, objective weights, provider, or budget changes.

## See Also

- `traigent-run-optimization` - cost limits, algorithms, and stop reasons.
- `traigent-analyze-results` - result fields, best config, cost, and stop-reason interpretation.
- `traigent-iterate` - decide what to change after a failed or inconclusive gate.

<!-- Reserved: managed longitudinal-guidance region. Step-level edits must not write here. -->
<!-- SLOW_UPDATE -->
<!-- /SLOW_UPDATE -->

<!-- INTERACTION_POLICY v1 (synced — do not edit inline; edit docs/shared/interaction-policy.v1.md) -->
## Traigent Interaction Policy
Track an interaction profile and adapt to it. Persona (stable): control=`delegate|guided|inspect`,
expertise=`se|ds|unknown`. Mood (this session): pace=`execute|balanced|explore`. Default when
unknown: `guided,se,balanced`. Infer from explicit user statements first, then recent behavior;
an explicit correction wins immediately. Never store or send this profile anywhere by default.

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
