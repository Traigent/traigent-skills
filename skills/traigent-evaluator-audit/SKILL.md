---
name: traigent-evaluator-audit
description: "Audit evaluator reliability before trusting Traigent optimization decisions. Use when users ask: is my LLM judge reliable, audit my evaluator, judge agreement, evaluator calibration, calibrate thresholds, parse-failure policy, repeated-judge stability, bias probes, or when optimization results depend on an LLM-as-judge metric."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0"
---

# Evaluator Audit

## When to Use

Use this skill before trusting an evaluator that drives optimization decisions, especially an LLM judge. Trigger it for:

- "is my LLM judge reliable?"
- "audit my evaluator"
- "judge agreement"
- "calibrate thresholds"
- "why are my optimization results noisy?"

## Why Audit

An unreliable evaluator silently corrupts every optimization decision downstream. If the judge rewards verbosity, misses parse failures, changes labels on repeated calls, or disagrees with humans on the target evaluation dataset, the optimizer can faithfully optimize the wrong thing.

Run the audit before the first real optimization, then re-run it whenever the judge model, prompt, output schema, scoring rubric, or evaluation dataset changes.

## Gold-Set Agreement

Build a 20-50 example human-labeled gold slice from the same evaluation dataset distribution the optimizer will use. Include easy, borderline, and known-bad cases. Lock the labels before inspecting judge outputs.

Minimum bars before trusting the judge as a primary optimizer objective:

- Parse success rate: at least 98% on the gold slice.
- Human agreement: at least 85% exact agreement for categorical pass/fail labels, or rank correlation above 0.70 for ordinal scores.
- False-pass rate on known-bad cases: low enough for the product risk. For safety or compliance gates, any repeated false pass is a blocker.
- Disagreement review: every disagreement gets a written reason, assigned to either human label error, ambiguous rubric, judge failure, or data ambiguity.

```python
from statistics import mean

def agreement_rate(gold_labels, judge_labels):
    pairs = list(zip(gold_labels, judge_labels, strict=True))
    return mean(1.0 if expected == observed else 0.0 for expected, observed in pairs)

gold = ["pass", "fail", "pass", "fail"]
judge = ["pass", "fail", "fail", "fail"]
print(f"agreement={agreement_rate(gold, judge):.1%}")
```

If the judge misses the bar, do not use it as the sole objective. Fix the rubric, add deterministic checks, or use it only as a diagnostic signal.

## Stability Across Repetitions

Run the same input through the same judge N times, with the same prompt, model version, sampling settings, and output schema. Use at least 3 repetitions for cheap judges and 5 for noisy judges.

Track:

- Score standard deviation for numeric outputs.
- Pass/fail flip rate for categorical outputs.
- Parse-failure count per repetition.
- Whether the same rationale supports the same label.

Demote the judge to statistical aggregation when repeated calls are unstable. Use mean or majority vote over repetitions, raise repetitions per trial, and report wider uncertainty. A single-call judge with high flip rate should not decide close candidates.

## Bias Probes

Probe known LLM-judge failure modes before optimization:

- Position bias: score answer A vs answer B, then swap order. A reliable pairwise judge should not change the winner only because the order changed.
- Length and verbosity bias: compare a concise correct answer against a verbose equivalent answer. The verbose answer should not win solely because it is longer.
- Self-preference: blind model identity and prompt style. If the judge favors outputs from its own family or from one template, use anonymized outputs and shuffle metadata.
- Tie sanity: compare an answer to itself. The judge should return a tie or equal score.
- Adversarial polish: compare a polished but wrong answer against a rough correct answer. The correct answer must not lose because it reads better.

These probes are drawn from the same failure modes discussed in the MT-Bench LLM-judge literature. Keep the probes in the audit artifact so future prompt or model changes can be rechecked.

## Parse-Failure Policy

Use a strict output schema. Count parse failures as first-class failures. FAIL-CLOSED: a parse failure is a score of 0 or an abstain, never a silent pass.

```python
import json
from typing import Any

REQUIRED_KEYS = {"score", "decision", "reason"}

def parse_judge_output(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
        missing = REQUIRED_KEYS - set(payload)
        if missing:
            raise ValueError(f"missing keys: {sorted(missing)}")
        if payload["decision"] not in {"pass", "fail", "abstain"}:
            raise ValueError("decision must be pass, fail, or abstain")
        payload["score"] = float(payload["score"])
        return {**payload, "parse_failed": False}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {
            "score": 0.0,
            "decision": "abstain",
            "reason": "parse failure",
            "parse_failed": True,
        }
```

Report parse-failure rate separately from model quality. A low score caused by parse failures calls for schema repair, not prompt or model tuning.

## Threshold Calibration

Sweep the judge threshold against the gold slice before using it in optimization. Choose the threshold that matches product risk:

- For quality ranking, maximize balanced accuracy or F1 on the gold slice.
- For safety gates, prefer lower false-pass rate even if recall drops.
- For noisy judges, require a margin: do not treat scores near the threshold as confident passes.

```python
def confusion_counts(gold_pass, scores, threshold):
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for expected_pass, score in zip(gold_pass, scores, strict=True):
        observed_pass = score >= threshold
        if expected_pass and observed_pass:
            counts["tp"] += 1
        elif not expected_pass and observed_pass:
            counts["fp"] += 1
        elif not expected_pass and not observed_pass:
            counts["tn"] += 1
        else:
            counts["fn"] += 1
    return counts

for threshold in [0.60, 0.70, 0.80, 0.90]:
    print(threshold, confusion_counts(gold_pass, judge_scores, threshold))
```

Lock the chosen threshold before running optimization. Do not tune the threshold on the same holdout used to claim the final result.

## When to Demote to Hybrid

Use a hybrid evaluator when the judge is useful but not reliable enough to own the whole metric:

1. Run deterministic gates first: schema validity, required fields, exact-match invariants, safety keyword blocks, citation presence, cost and latency caps.
2. Send only the residue to the LLM judge.
3. Treat deterministic failures as hard failures.
4. Aggregate judge outputs statistically when repeated calls are noisy.
5. Report deterministic-fail, parse-fail, judge-fail, and judge-pass counts separately.

Hybrid evaluation is the default for high-risk workflows: deterministic gates protect non-negotiable behavior, and the judge handles semantic residue.

## Claim Scope

Audit results hold only for the audited evaluation dataset distribution, judge model version, judge prompt, output schema, sampling settings, and threshold. Re-audit on any model, prompt, schema, rubric, or dataset-distribution change.

## See Also

- `traigent-build-evaluator` - build the evaluator before auditing it.
- `traigent-choose-metric` - choose objectives and weights before threshold calibration.
- `traigent-curate-dataset` - synthesize harder cases when the gold slice is too easy or ambiguous.
