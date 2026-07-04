# Gate Workflow

Copy this workflow into `.github/workflows/traigent-safety-gate.yml` and adapt the two `scripts/run_holdout_eval.py` calls to your project (a reference implementation is provided below — the gate does not work without it). The config files are the export artifacts from the lifecycle skill: `configs/baseline.json` is the pinned incumbent, and `configs/candidate.json` is the `export_config("candidate_config.json")` artifact from the winning run, committed by the PR under review. Each run should write JSON with this shape:

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

jobs:
  pr-offline-wiring:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    env:
      TRAIGENT_OFFLINE_MODE: "true"
      TRAIGENT_RUN_COST_LIMIT: "0.00"
      # Required for ANY offline/mock optimize() under CI=true — without it
      # the SDK raises OptimizationError and this job red-fails on every PR.
      TRAIGENT_RUN_APPROVED: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -r requirements.txt
      - name: Validate TVL specs
        run: python -m traigent.tvl tvl/ --strict
      - name: Run incumbent holdout in mock mode
        run: python scripts/run_holdout_eval.py --mode mock --config configs/baseline.json --output .gate/incumbent.json
      - name: Run candidate holdout in mock mode
        run: python scripts/run_holdout_eval.py --mode mock --config configs/candidate.json --output .gate/candidate.json
      - name: Check safety and efficiency wiring
        run: python scripts/traigent_gate.py --incumbent .gate/incumbent.json --candidate .gate/candidate.json --max-cost 0.01 --max-latency-ms 1200

  # Set TRAIGENT_API_KEY in your repository's CI secrets.
  # See: https://github.com/your-org/your-repo/settings/secrets/actions
  # For how to obtain the key, see the traigent-setup-quickstart skill:
  #   skills/traigent-setup-quickstart/SKILL.md#get-your-traigent-api-key
  nightly-real-holdout:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    env:
      TRAIGENT_RUN_COST_LIMIT: "5.00"
      TRAIGENT_API_KEY: ${{ secrets.TRAIGENT_API_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -r requirements.txt
      - name: Validate TVL specs
        run: python -m traigent.tvl tvl/ --strict
      - name: Run incumbent holdout
        run: python scripts/run_holdout_eval.py --config configs/baseline.json --output .gate/incumbent.json
      - name: Run candidate holdout
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
import time
from pathlib import Path


def evaluate_one(example: dict, config: dict, mode: str) -> tuple[float, float, float]:
    """Return (accuracy, latency_ms, cost) for one holdout example.

    ADAPT THIS: apply `config` to your agent and call it. In --mode mock
    return canned values without touching any provider (zero spend).
    """
    if mode == "mock":
        return 1.0, 0.0, 0.0
    start = time.perf_counter()
    output = run_my_agent(example["input"], config)  # <- your agent call
    latency_ms = (time.perf_counter() - start) * 1000.0
    accuracy = 1.0 if output.strip() == example["expected_output"].strip() else 0.0
    return accuracy, latency_ms, 0.0  # supply real per-call cost if you track it


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, default=Path("eval/holdout.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["real", "mock"], default="real")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    accuracy: list[float] = []
    latency: list[float] = []
    total_cost = 0.0
    for line in args.holdout.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        score, ms, cost = evaluate_one(json.loads(line), config, args.mode)
        accuracy.append(score)
        latency.append(ms)
        total_cost += cost

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
    value = metrics.get(name)
    if value is None:
        raise SystemExit(f"missing metric: {name}")
    if isinstance(value, list):
        series = [float(item) for item in value]
    else:
        series = [float(value)]
    if not series:
        raise SystemExit(f"empty metric series: {name}")
    return series

def cost(payload: dict[str, Any]) -> float:
    value = payload.get("total_cost", payload.get("cost", 0.0))
    return float(value or 0.0)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incumbent", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--max-cost", type=float, required=True)
    parser.add_argument("--max-latency-ms", type=float, required=True)
    parser.add_argument("--require-promote", action="store_true")
    args = parser.parse_args()

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

The PR job verifies wiring in offline/mock mode. The scheduled job runs the real holdout under `TRAIGENT_RUN_COST_LIMIT` and fails on promotion rejection, required-promotion no-decision, regression, budget breach, missing metrics, or latency breach.
