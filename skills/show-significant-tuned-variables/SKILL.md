---
name: show-significant-tuned-variables
description: "Show significant tuned variables and rank which variables mattered in a Traigent optimization. Use for: show significant tuned variables, which variables mattered, tuned variable importance, feature importance for optimization, optimization gains attribution, parameter importance with honest confidence labels, or one-glance video card summaries of what drove optimization gains."
license: Apache-2.0
metadata:
  author: Nimrod
  version: "1.0"
---

# Show Significant Tuned Variables

## Purpose

Use this skill to explain which tuned variables actually drove an optimization's observed gains. It ranks configuration knobs by effect size, adds honest confidence labels, and emits a one-glance SVG video card suitable for demos or review.

The bundled script is designed for Traigent text2sql demo artifacts but works with any JSONL trial file that has a numeric objective and a `config` object.

## When to Use

Use this skill when the user asks:

- "show significant tuned variables"
- "which variables mattered?"
- "tuned variable importance"
- "feature importance for optimization"
- "what drove the optimization gains?"
- "make a video card for the important knobs"

## Inputs

The script accepts:

- `--trials`: required JSONL, one trial per line. Each row must contain `config` and a numeric objective such as `accuracy`.
- `--config-space`: optional JSON object `{knob: [values...]}`. If absent, the script infers knobs and values observed in trials.
- `--heldout`: optional heldout report JSON with `baseline`, `optimized`, and `delta`. When present, the video card uses the heldout optimized-vs-baseline accuracy and cost deltas for context.
- `--objective`: objective field to maximize, typically `accuracy`.

Expected trial shape:

```json
{"accuracy": 0.58, "config": {"schema_context": "linked_top10", "fewshot_k": 5}, "mock_cost": 0.02052, "correct": 7, "total": 12, "trial_index": 8}
```

## Outputs

The script writes these files into `--output-dir`:

- `importance.json`: ranked tuned variables with `knob`, `spread`, `variance_share`, `ci_low`, `ci_high`, `label`, `best_value`, `best_value_mean_acc`, and `cost_effect`.
- `importance.csv`: flat CSV with the same fields.
- `significant_variables.svg`: hand-written 1280x720 dark-theme SVG with horizontal bars, bootstrap CI whiskers, best-value annotations, and a directional/significance caption.
- `insights.md`: short human-readable summary using honest claim language.
- `video_card.json`: compact payload: `top_variables`, `n_trials`, `objective`, and `caption`.

## Honesty Rule

Never overclaim significance:

- With fewer than 20 trials, importances are labelled `directional`, not statistically significant.
- A variable is called `significant` only if its bootstrap CI lower bound is greater than 0.
- The ranking is observational: "on this fixed Spider slice, in this run." It is not proof of causal attribution.

The primary importance is the spread between the best and worst per-value mean objective. The script also reports variance-decomposition share: between-group variance divided by total variance.

## Worked Example

Run with the Python interpreter where you installed the Traigent SDK (`python3`, or your project's `.venv/bin/python`):

```bash
python3 skills/show-significant-tuned-variables/scripts/significant_tuned_variables.py \
  --trials /path/to/02_trials.jsonl \
  --heldout /path/to/07_heldout_report.json \
  --objective accuracy \
  --top-k 4 \
  --confidence 0.9 \
  --output-dir /tmp/significant-tuned-variables
```

Then inspect:

```bash
cat /tmp/significant-tuned-variables/importance.json
cat /tmp/significant-tuned-variables/video_card.json
```

## Method Notes

For each knob, the script groups trials by the knob's value, computes mean objective per value, ranks by the max-min spread, and reports variance share as a companion statistic. Bootstrap confidence intervals use trial resampling with replacement and fixed seed `55`.

The script also attempts to adapt trials to `traigent.utils.importance.ParameterImportanceAnalyzer` for a variance-based SDK cross-check. If that adaptation is unavailable or returns no output, it skips gracefully and states that the skill's own variance/bootstrap method was used, inspired by the SDK analyzer. Do not fabricate SDK analyzer output.
