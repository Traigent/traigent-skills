---
name: traigent-results-consolidation
description: "Consolidate every optimization run over the same test domain into one sortable Excel workbook (one row per eval) for cross-run analysis. Use when you have several runs (same dataset/domain) and want a single master sheet: run designator + permutation count + batch/eval sequence, KPIs, decomposed model, and the UNION of all knobs across runs. Builds from run logs for convenient local/offline analysis."
license: Apache-2.0
metadata:
  author: Amir
  version: "1.0"
---

# Traigent results consolidation — all runs, one workbook

When you've done several runs over the **same test domain** (e.g. SPIDER
text2SQL), put every eval into ONE sortable sheet so you can compare across runs,
weights, models, and knob sets. This also works when the portal didn't capture a
run — parse the run logs (the trial table is always printed locally).

> The workbook is not the end — it's the **input to a decision the user must
> see.** As runs accumulate, the conclusions it implies for the NEXT run (which
> models and knobs to keep / drop / add, and the weight shift) must be **derived
> and PRESENTED to the user** before the next run plan is filled. Don't leave
> those conclusions sitting in a sheet. See `traigent-knob-iteration` §5 and the
> reference `analyze_runs.py` (prints + writes `NEXT_RUN_RECOMMENDATIONS.md`).

## Column contract (left -> right)
1. **run** — a unique designator for the optimization run. **Include the
   permutation count (config-space size) IN the run name**, e.g.
   `A | ACL 80/15/05 | oldknobs | 216 perms | <exp-id>`.
2. **permutations** — the config-space size (product of value-counts over all
   tuned knobs) as its **own column, placed right next to `run`**. Always present.
3. **seq** — `<batch-letter><eval#>` (e.g. `A1`, `B7`, `I25`). Letter = run in
   chronological batch order; number = eval within that run.
4. **KPIs** — `weighted_score`, `accuracy`, `cost_usd`, `latency_s`.
5. **model** — `model_full`, then decomposed: `model_name`, `model_number`,
   `model_vendor`.
6. **knobs** — ALL model knobs first incl. implicit ones (`temperature`, `top_p`,
   `max_tokens`, `reasoning_effort`), then structural knobs as the **UNION across
   all runs, in first-appearance order** (first run's knobs, then each later run's
   new knobs). Blank where a run didn't have that knob.

> The permutation count appears **twice on purpose**: as a sortable column (to
> filter/compare by search-space size) and inside the run name (to read at a glance).
> Source it from the run's printed `config-space size: N`.

All headers get an **auto-filter** (sortable) and frozen panes. Add a second
**Runs** sheet legending each batch (log, experiment, weights, knobset, #evals,
notes) and the `weighted_score` formula.

## Include rule
Only runs over the **same test data/domain** with **> 3 evals** (skip 1-3 eval
smoke/validate/probe runs). Order runs chronologically (run-id timestamp) to
assign batch letters A, B, C...

## weighted_score (when per-trial composite isn't in the log)
Compute per run, documented in the sheet:
```
weighted_score = w_acc*accuracy + w_cost*cost_benefit + w_lat*lat_benefit
  *_benefit = per-run min-max of the minimized metric; absent/constant -> 1.0 (neutral)
```
Use each run's own ACL weights.

## Parsing tip
Parse the run log's trial table **header-driven** (map column NAMES to indices) —
column layout varies between runs (e.g. the `latency` column is absent when
latency isn't an objective). Dedupe the table (it's printed twice) by trial #.

## Implementation
A ready script lives at `agent/build_master_xlsx.py` (openpyxl): edit the `RUNS`
list (chronological) and `MODEL_MAP`, run it, get `*_ALL_runs_master.xlsx`.

## See also
- `traigent-knob-iteration` — the consolidated sheet is the input to knob-impact analysis.
- `traigent-analyze-results` — SDK-native result inspection.
