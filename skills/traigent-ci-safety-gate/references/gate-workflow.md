# Gate Workflow

Copy this workflow into `.github/workflows/traigent-safety-gate.yml` and adapt the two `scripts/run_holdout_eval.py` calls to your project (a reference implementation is provided below — the gate does not work without it). The config files are the export artifacts from the lifecycle skill: `configs/baseline.json` is the pinned incumbent, and `configs/candidate.json` is the `export_config("candidate_config.json")` artifact from the winning run, committed by the PR under review — note that `export_config` writes a wrapper (`{"config": {...}, ...}`), not a flat configuration, so the reference script below unwraps it. Each run should write JSON with this shape:

```json
{
  "metrics": {
    "accuracy": [0.81, 0.82, 0.80],
    "latency_ms": [880, 900, 870]
  },
  "total_cost": 1.23
}
```

## GitHub Actions Workflow

```yaml
name: Traigent Safety Gate

on:
  pull_request:
    paths:
      - "agent/**"
      - "configs/**"
      - "eval/**"
      - "scripts/**"
      - "tvl/**"
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  pr-offline-wiring:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    env:
      TRAIGENT_OFFLINE_MODE: "true"
      # Required for ANY offline/mock optimize() under CI=true — without it,
      # any such call your run_holdout_eval.py makes raises OptimizationError
      # and red-fails the job.
      TRAIGENT_RUN_APPROVED: "1"
      # TRAIGENT_RUN_COST_LIMIT is deliberately NOT set here. The SDK rejects a
      # non-positive limit (`ConfigurationError: ... must be > 0 USD`) as soon as
      # the cost enforcer is built, so "0.00" would red-fail the first offline
      # optimize()/optimize_sync() call this job reaches. The YAML never calls
      # it directly -- only your own run_holdout_eval.py would, and the
      # reference implementation in references/gate-workflow.md does not, which
      # is the only reason "0.00" was ever green here. A token cap such as
      # "0.01" can fail too, because the pre-run check uses a conservative
      # estimate even offline -- measured at $0.32 for a two-row dataset and
      # two grid trials, so scale the figure to your job before trusting it.
      # Leave it unset (the $2.00 default) and rely on
      # TRAIGENT_OFFLINE_MODE for zero spend; set a cap only in the paid job,
      # above the estimate for its dataset and trial count.
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -r requirements.txt
      - name: Validate TVL specs (fail if none found)
        run: |
          set -euo pipefail
          mapfile -t specs < <(find tvl -name '*.tvl.yml' -o -name '*.tvl.yaml' 2>/dev/null)
          [ "${#specs[@]}" -gt 0 ] || { echo "no *.tvl.yml specs under tvl/" >&2; exit 1; }
          python -m traigent.tvl "${specs[@]}" --strict --verbose
      - name: Run incumbent holdout in mock mode
        run: python scripts/run_holdout_eval.py --mode mock --config configs/baseline.json --output .gate/incumbent.json
      - name: Run candidate holdout in mock mode
        run: python scripts/run_holdout_eval.py --mode mock --config configs/candidate.json --output .gate/candidate.json
      - name: Check safety and efficiency wiring
        run: python scripts/traigent_gate.py --incumbent .gate/incumbent.json --candidate .gate/candidate.json --max-cost 0.01 --max-latency-ms 1200

  # Store the provider key your agent calls (OPENAI_API_KEY below) in the
  # repository's CI secrets and pass it only to the steps that call the agent,
  # never at job level, where every step (including package installs) sees it.
  # Add TRAIGENT_API_KEY to those steps' env only if your run_my_agent uses a
  # Traigent-backed path; the gate script itself runs locally. For how to
  # obtain a Traigent key, see the traigent-setup-quickstart skill:
  #   skills/traigent-setup-quickstart/SKILL.md#get-your-traigent-api-key
  nightly-real-holdout:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    env:
      TRAIGENT_RUN_COST_LIMIT: "5.00"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -r requirements.txt
      - name: Validate TVL specs (fail if none found)
        run: |
          set -euo pipefail
          mapfile -t specs < <(find tvl -name '*.tvl.yml' -o -name '*.tvl.yaml' 2>/dev/null)
          [ "${#specs[@]}" -gt 0 ] || { echo "no *.tvl.yml specs under tvl/" >&2; exit 1; }
          python -m traigent.tvl "${specs[@]}" --strict --verbose
      - name: Run incumbent holdout
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}   # the provider your agent calls
        run: python scripts/run_holdout_eval.py --config configs/baseline.json --output .gate/incumbent.json
      - name: Run candidate holdout
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: python scripts/run_holdout_eval.py --config configs/candidate.json --output .gate/candidate.json
      - name: Enforce promotion, safety, and efficiency
        run: python scripts/traigent_gate.py --incumbent .gate/incumbent.json --candidate .gate/candidate.json --max-cost 5.00 --max-latency-ms 1200 --require-promote
```

## Holdout Eval Script

Save this as `scripts/run_holdout_eval.py`. Only `evaluate_one` is project-specific — adapt it to call your agent with the config applied; everything else (arg parsing, JSONL loop, output shape) matches what `traigent_gate.py` consumes.

```python
#!/usr/bin/env python3
"""Reference implementation — adapt evaluate_one() to your agent."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


# `export_config(...)` does NOT write a flat configuration: it writes a wrapper.
# format="slim" (the default) writes {"config", "function_name", "exported_at",
# "traigent_version", "metrics"}; format="full" adds "trials", "optimization"
# and "configuration_space"; include_metadata=False writes a bare
# {"config": {...}} with no "exported_at", so never key the unwrap on that field.
_EXPORT_WRAPPER_KEYS = {
    "config", "function_name", "exported_at", "traigent_version", "metrics",
    "trials", "optimization", "configuration_space",
}
# Keys only an export carries. A document with any of these is a wrapper, even
# if its "config" is missing -- which is what tells us to refuse rather than
# hand the envelope to the agent. "metrics" and "config" are excluded: both are
# plausible knob names in a genuinely flat configuration.
_EXPORT_MARKER_KEYS = _EXPORT_WRAPPER_KEYS - {"config", "metrics"}

# The SDK accepts several label keys and resolves them in this order
# (traigent.evaluators.base._EXPECTED_OUTPUT_FIELDS). The datasets the other
# skills teach use "output", so read the same keys in the same order.
_EXPECTED_OUTPUT_FIELDS = ("output", "expected", "expected_output", "answer", "target", "label")
# Same for the input side: the SDK takes "input", else "input_data", and
# `traigent-dataset-curate` tells readers both are accepted.
_INPUT_FIELDS = ("input", "input_data")


def unwrap_config(doc: object) -> dict:
    """Accept either an export_config artifact or an already-flat config.

    Fails closed on an unrecognised wrapper key instead of guessing. Silently
    treating an unknown wrapper as a flat config is the original defect wearing
    a new shape: the agent is handed the envelope, applies none of the tuned
    values, and the gate still emits a promotion decision.

    An EMPTY config is allowed -- a pinned incumbent may legitimately mean
    "the agent's own defaults". If you want to refuse a candidate that applies
    nothing, assert it in the workflow, not here.

    Known limit: a genuinely flat config whose own knobs are named only from
    the wrapper vocabulary (a knob called `config` holding a dict, beside one
    called `metrics`) is indistinguishable from a wrapper and will be
    unwrapped. Rename such a knob, or pass the config already unwrapped.
    """
    if not isinstance(doc, dict):
        raise SystemExit(f"config file must contain a JSON object, got {type(doc).__name__}")
    # Wrapper-ness is decided by a marker only an export carries, never by the
    # presence of a readable `config`. Keying on `config` alone let a wrapper
    # whose config key was absent, null or renamed fall through as a flat
    # config, which is the same silent pass-through in a new costume.
    markers = sorted(set(doc) & _EXPORT_MARKER_KEYS)
    # include_metadata=False writes a bare {"config": {...}} with no marker at
    # all, so that exact shape counts as a wrapper too -- and only that shape,
    # since any extra key would make it indistinguishable from a flat config.
    bare = set(doc) == {"config"} and isinstance(doc.get("config"), dict)
    if not markers and not bare:
        return doc
    unknown = sorted(set(doc) - _EXPORT_WRAPPER_KEYS)
    if unknown:
        raise SystemExit(
            f"config file looks like an export_config wrapper (has {markers}) but carries "
            f"unrecognised keys {unknown}; refusing to guess. Re-export it, or pass the "
            "inner config."
        )
    if not isinstance(doc.get("config"), dict):
        raise SystemExit(
            f"config file looks like an export_config wrapper (has {markers}) but its "
            "'config' key is missing or not an object; refusing to run the agent on the "
            "envelope. Re-export it, or pass the inner config."
        )
    return doc["config"]


def expected_output(example: dict):
    """Return the row's label, using the SDK's own key precedence."""
    for key in _EXPECTED_OUTPUT_FIELDS:
        if key in example:
            return example[key]
    raise SystemExit(
        f"holdout row has no label key; expected one of {list(_EXPECTED_OUTPUT_FIELDS)}, got {sorted(example)}"
    )


def model_input(example: dict):
    """Return the row's input, using the SDK's own key precedence."""
    for key in _INPUT_FIELDS:
        if key in example:
            return example[key]
    raise SystemExit(
        f"holdout row has no input key; expected one of {list(_INPUT_FIELDS)}, got {sorted(example)}"
    )


def matches(output, expected) -> float:
    """A deliberately simple exact match: case-insensitive and
    whitespace-trimmed when BOTH sides are strings, plain equality otherwise.

    This is NOT the SDK's optimizer-side accuracy, which additionally coerces a
    string output toward the label's type and compares containers element-wise.
    The gap matters whenever the value is numeric or structured in any
    representation. The optimizer coerces a JSON-text output toward a dict/list
    label, and coerces a numeric string pair ("4.0" vs "4") to numbers; this
    gate scores both 0.0, so it would reject a candidate that genuinely won.
    If your labels are dicts, lists or numbers -- including numbers stored as
    strings, the common JSONL habit -- parse both sides here before comparing."""
    if isinstance(output, str) and isinstance(expected, str):
        return 1.0 if output.strip().lower() == expected.strip().lower() else 0.0
    return 1.0 if output == expected else 0.0


def evaluate_one(example: dict, config: dict, mode: str) -> tuple[float, float, float | None]:
    """Return (accuracy, latency_ms, cost) for one holdout example.

    ADAPT THIS: apply `config` to your agent and call it. In --mode real, cost
    must be the MEASURED USD of this call (for a LiteLLM agent:
    `litellm.completion_cost(response)`; otherwise price the usage the provider
    returned) or None when it could not be measured — never a 0.0 placeholder,
    which would make the budget check pass on nothing.

    --mode mock still reads the row's input and label before returning canned
    values (and main() has already validated the config shape for both modes),
    so the zero-spend PR job catches a bad config shape or a bad row key -- the
    two that used to surface only at 03:00. It does NOT call run_my_agent, so a
    broken adapter still surfaces first in the paid job.
    """
    expected = expected_output(example)
    value = model_input(example)
    if mode == "mock":
        return 1.0, 0.0, 0.0
    start = time.perf_counter()
    output, cost = run_my_agent(value, config)  # <- your agent call; return its measured cost too
    latency_ms = (time.perf_counter() - start) * 1000.0
    return matches(output, expected), latency_ms, cost


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, default=Path("eval/holdout.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["real", "mock"], default="real")
    args = parser.parse_args()

    config = unwrap_config(json.loads(args.config.read_text(encoding="utf-8")))
    accuracy: list[float] = []
    latency: list[float] = []
    total_cost = 0.0
    for line in args.holdout.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        score, ms, cost = evaluate_one(json.loads(line), config, args.mode)
        if cost is None:
            raise SystemExit("unmeasured call cost: the efficiency check cannot pass on a guess")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise SystemExit(f"call cost must be finite and nonnegative: {cost!r}")
        accuracy.append(score)
        latency.append(ms)
        total_cost += cost
    if args.mode == "real" and total_cost == 0.0:
        raise SystemExit("total_cost is 0.0 after real calls: cost is not wired, the budget check cannot pass on nothing")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "metrics": {"accuracy": accuracy, "latency_ms": latency},
        "total_cost": total_cost,
    }), encoding="utf-8")


if __name__ == "__main__":
    main()
```

## Gate Script

Save this as `scripts/traigent_gate.py`.

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from traigent.tvl.models import PromotionPolicy
from traigent.tvl.promotion_gate import ObjectiveSpec, PromotionGate

OBJECTIVES = [
    ObjectiveSpec(name="accuracy", direction="maximize"),
    ObjectiveSpec(name="latency_ms", direction="minimize"),
]

def load_payload(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return payload

def metric_series(payload: dict[str, Any], name: str) -> list[float]:
    metrics = payload.get("metrics", payload)
    if not isinstance(metrics, dict):
        raise SystemExit(f"metrics must be an object: {name}")
    value = metrics.get(name)
    if value is None:
        raise SystemExit(f"missing metric: {name}")
    values = value if isinstance(value, list) else [value]
    if not values:
        raise SystemExit(f"empty metric series: {name}")
    series = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SystemExit(f"invalid metric {name}: {item!r}")
        number = float(item)
        if not math.isfinite(number) or number < 0 or (name == "accuracy" and number > 1):
            raise SystemExit(f"invalid metric {name}: {item!r}")
        series.append(number)
    return series

def cost(payload: dict[str, Any]) -> float:
    value = payload.get("total_cost", payload.get("cost"))
    if value is None:
        raise SystemExit("missing total_cost: the budget check cannot pass on an unmeasured cost")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"invalid total_cost: {value!r}")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise SystemExit(f"non-finite or negative total_cost: {value!r}")
    return value

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incumbent", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--max-cost", type=float, required=True)
    parser.add_argument("--max-latency-ms", type=float, required=True)
    parser.add_argument("--require-promote", action="store_true")
    args = parser.parse_args()

    for name, value in (("--max-cost", args.max_cost), ("--max-latency-ms", args.max_latency_ms)):
        if not math.isfinite(value) or value < 0:
            raise SystemExit(f"{name} must be finite and nonnegative")

    incumbent_payload = load_payload(args.incumbent)
    candidate_payload = load_payload(args.candidate)

    candidate_cost = cost(candidate_payload)
    if candidate_cost > args.max_cost:
        print(f"budget breach: cost={candidate_cost:.4f} max={args.max_cost:.4f}", file=sys.stderr)
        return 2

    candidate_latency = metric_series(candidate_payload, "latency_ms")
    mean_latency = statistics.mean(candidate_latency)
    if mean_latency > args.max_latency_ms:
        print(f"latency breach: mean={mean_latency:.1f} max={args.max_latency_ms:.1f}", file=sys.stderr)
        return 2

    policy = PromotionPolicy(
        dominance="epsilon_pareto",
        alpha=0.05,
        min_effect={"accuracy": 0.01, "latency_ms": 25.0},
        adjust="BH",
    )
    gate = PromotionGate(policy=policy, objectives=OBJECTIVES)
    decision = gate.evaluate(
        incumbent_metrics={
            "accuracy": metric_series(incumbent_payload, "accuracy"),
            "latency_ms": metric_series(incumbent_payload, "latency_ms"),
        },
        candidate_metrics={
            "accuracy": metric_series(candidate_payload, "accuracy"),
            "latency_ms": candidate_latency,
        },
    )

    print(f"promotion_decision={decision.decision}")
    print(f"reason={decision.reason}")

    if decision.decision == "reject":
        return 1
    if args.require_promote and decision.decision != "promote":
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

The PR job verifies wiring in offline/mock mode. The scheduled job evaluates the real holdout
and fails on promotion rejection, required-promotion no-decision, regression, budget breach,
missing or invalid measurements, or latency breach. `--max-cost` checks the completed candidate's
spend; it does not stop provider calls. `TRAIGENT_RUN_COST_LIMIT` governs SDK-managed optimization,
not arbitrary calls inside `run_my_agent`. Before enabling real mode, implement spending control
in that project-specific adapter, covering both the incumbent and candidate evaluations.
