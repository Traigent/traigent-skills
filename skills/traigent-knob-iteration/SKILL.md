---
name: traigent-knob-iteration
description: "Iterate an optimization run-over-run by measuring which knobs actually moved accuracy, dropping the dead ones, and swapping in higher-value structural knobs. Use after a run (Setup Guide Part H) to rank knob impact across pooled trials and design the next config space. Captures the swap that lifted text2SQL from 83.3% -> 90%."
license: Apache-2.0
metadata:
  author: Amir
  version: "1.0"
---

# Traigent knob iteration — drop the dead, swap in the effective

The highest-leverage step in optimization is **changing the config space between
runs**, not running the same space longer. This skill is the concrete loop.

## 1. Measure per-knob impact on the objective you care about
Pool trials across comparable runs (more trials = more signal) and, for each
knob, compute the spread of mean accuracy across its values:

```python
for knob in KNOBS:
    groups = defaultdict(list)
    for t in trials: groups[t[knob]].append(t["accuracy"])
    means = {v: mean(a) for v, a in groups.items()}
    impact = max(means.values()) - min(means.values())   # bigger = mattered more
```
Watch for **fake impact**: a knob whose high spread comes from n=1 outliers
(e.g. stray values from an unintended continuous encoding — string-encode
discrete knobs to avoid this) hasn't really mattered — look at the discrete
values with adequate n.

## 2. Decide drops and adds
- **Drop** knobs with ~zero impact AND a cost (they only waste the budget).
  In text2SQL we found `schema_context` (sample rows: 0.001 impact) and
  `candidate_count` (self-consistency: ~0 accuracy, +cost) were dead.
- **Add** evidence-backed structural knobs from the task taxonomy
  (`traigent-structural-spine`). We swapped in:
  - `fewshot_selector`: `fixed` vs `similar` (pick exemplars most similar to the
    question — DAIL-style; dependency-free Jaccard works).
  - `generation_path`: `direct` vs `plan_then_sql` (brief query plan/CoT, then SQL).
- Keep the proven movers (`model`, `fewshot_k`, `repair`, `temperature`).

## 3. Re-run and confirm the swap paid off
Re-run the same weights/dataset with the new space, then check the new knobs'
marginal means AND whether they appear in the top configs:
- `fewshot_selector`: similar **80%** vs fixed 75% (+5)
- `generation_path`: plan_then_sql **80%** vs direct 75% (+5)
- best config stacked both -> **90%** (was 83.3% with the old knobs).

## 4. Report honestly
- With <~20 trials call results **directional**, not significant (Part H).
- Per-knob marginals average over the other knobs/models — with N trials over M
  models, each model is sampled sparsely; note coverage caveats.
- Keep the dataset and weights FIXED across the compared runs, or you're not
  measuring the knob.

## 5. PRESENT the next-run conclusions to the user (mandatory)
As run data accumulates in the workbook, the conclusions about **what the next
run should look like** must be **exposed and presented to the user — not buried in
a sheet.** After EVERY run, derive from the pooled data and show the user:
- **Models**: which to KEEP (highest accuracy / best accuracy-per-$), which to
  DROP (dominated: lower accuracy and not cheaper), which tier to try next.
- **Knobs**: which MOVED accuracy (keep/widen), which are near-dead (drop, esp. if
  they add cost), and candidate NEW structural knobs to ADD.
- **Weights**: keep accuracy-first while the ceiling is still rising; shift toward
  cost once it plateaus (P5).
- **Best config so far** + its accuracy/cost.
Then seed the NEXT run plan's `MODELS` / `KNOB_*` / `ACL_WEIGHTS` / `CARRY_FORWARD`
from these conclusions — and still ASK the user about every option
(`traigent-run-plan`); the analysis informs the choices, it does not replace the
user's say. A reference engine: `analyze_runs.py` prints this and writes
`results/NEXT_RUN_RECOMMENDATIONS.md` automatically after each run.

## See also
- `traigent-structural-spine` — the catalog of task-level knobs to draw from.
- `show-significant-tuned-variables` / `traigent-analyze-results` — SDK-native ranking.
- `traigent-results-consolidation` — pool runs into one sortable workbook to do this analysis.
