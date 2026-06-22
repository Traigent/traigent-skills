---
name: traigent-next-run
description: "After EVERY Traigent run, give the user the portal experiment link and recommend the next run — which models to keep/drop, which knobs moved the metric vs are dead (drop/add), the best config so far, and how to shift the objective weights. Then fold the user's decisions into the next run-plan. Results live in the Traigent portal — share the experiment link after each run."
license: Apache-2.0
metadata:
  author: Traigent
  version: "1.0"
---

# Traigent next-run — share the portal link, recommend what's next

After every run, do two things: (1) hand the user the **portal experiment link** so
their results live in Traigent, and (2) recommend the next run. Then loop back to
`traigent-run-plan` to build that next run WITH the user.

**Terminology (use consistently):** a **run** is one optimization search; it
evaluates several **configs** (each config = one model + knob-value choice = one
result row); each config is scored on the testbed **samples** (one sample = one
config × one test example). "Best config", not "best eval"; "N samples", not "N evals".

## 1. Share the portal results (the durable record lives in the portal)
- Give the user the run's **portal `View` link** (printed by the SDK / in the portal
  under Experiments). That is their shareable, durable record:
  **Best Performers · the Pareto-optimal frontier · parameter importance · the
  Decision tab.**
- The portal is the durable home for results across runs — **always point the user
  to the `View` link.** (Confirm each run registered with its trials; if a run
  doesn't appear, it's likely a temporary connectivity issue — retry and confirm the
  link populates.)

## 2. Recommend the next run (present these to the user)
From the run's results (the trial table + the portal), tell the user:
- **Models** — which to KEEP (highest accuracy / best accuracy-per-$), which to DROP
  (dominated: lower accuracy and not cheaper), which tier to try next.
- **Knobs** — which **moved** the metric (keep / widen) and which are **dead** (drop,
  especially if they add cost); propose **new structural knobs** the evidence supports.
- **Best config so far** — and its accuracy / cost / latency.
- **Objective weights** — keep accuracy-first while the ceiling is still rising; shift
  toward cost once it plateaus (to find the cheapest near-equal config).
- **Honesty** — with < ~20 trials, label results *directional*, not significant; small
  testbeds (< ~30–50) have wide error bars — say so.

## 3. Loop
Use these conclusions to PROPOSE the next run's models/knobs/weights, then build that
plan WITH the user (`traigent-run-plan`) — they confirm every option.

## See also
`traigent-run-plan` · `traigent-iterate` · `traigent-structural-spine` (knob catalog) · `traigent-choose-metric`
