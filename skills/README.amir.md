# Traigent text2SQL optimization — captured skills (for the setup docs)

Field-tested skills distilled from optimizing a SPIDER text2SQL agent end-to-end
(plain agent **66.7% -> 90.0%** on the cheap model). Written in the same
`SKILL.md` format as `Traigent/traigent-skills` so they can fold into the
official setup docs / skill set.

| Skill | What it captures |
|---|---|
| [traigent-optimization-principles](traigent-optimization-principles/SKILL.md) | **The key recommendations (P1-P13):** span model tiers (incl. a full vendor ladder), >=3 structural knobs, record every model knob (even implicit/effort), drop dead knobs, vary the weights, record+name every run — plus the trustworthiness practices. **Read first.** |
| [traigent-run-plan](traigent-run-plan/SKILL.md) | **MANDATORY pre-run protocol:** before EVERY run, render a fresh run plan and ASK the user about **ALL** SDK options (objectives, weights, models, knobs, algorithm, trials, budget, execution_mode [default hybrid], privacy, injection, plateau, reps, timeout, fallback, …) — accept default or choose, never set any silently. |
| [traigent-text2sql-optimize](traigent-text2sql-optimize/SKILL.md) | The working end-to-end recipe: execution-match scoring, multi-field inputs, model + structural knobs, weighted ACL objectives, mock-then-real run. |
| [traigent-next-run](traigent-next-run/SKILL.md) | Measure which knobs moved accuracy, drop the dead ones, swap in better structural knobs (the swap that went 83.3% -> 90%). |
| [traigent-next-run](traigent-next-run/SKILL.md) | Consolidate all runs over one domain into a single sortable master workbook (one row per eval, incl. permutation count per run). |
| [traigent-run-recommendations](traigent-run-recommendations/SKILL.md) | Recommended setup for smooth, accurate, portal-tracked runs: robust knob encoding, cost/latency metering, execution mode, run naming with permutation count, light troubleshooting. |

**Headline method:** optimize -> measure what mattered -> drop dead knobs, add
effective ones -> re-optimize. The accuracy came from **prompt-structure knobs on
a cheap model** (similar few-shot + plan-then-SQL + repair), not a premium model —
so it's both more accurate and far cheaper.

Companion artifacts in the repo:
- `agent/optimize_txt2sql.py`, `agent/sql_agent.py` — the instrumented agent.
- `agent/build_master_xlsx.py` -> `SPIDER_text2sql_ALL_runs_master.xlsx` — all evals
  (one row per eval; run designator + permutation count + KPIs + model + all knobs).
