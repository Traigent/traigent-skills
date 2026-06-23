# Terminal-First Analytics — MCP Tool Contract

This reference documents the `traigent-analytics` MCP server the skill orchestrates when a
run lives in the Traigent cloud/portal. The skill's job is to **call the right tool at the
right moment and narrate the result** — it must not compute analytics, rank trials, fit a
Pareto frontier, or run any auth/tenant logic itself. All of that lives behind the MCP
server, which resolves the caller's tenant from the authenticated session, not from any
argument the skill passes.

> **Availability.** The keystone `analytics_get_run_decision_brief` and the
> `analytics_render_chart` tools ship first. The single-run drilldown tools
> (`analytics_get_single_run_pareto`, `analytics_get_run_leaderboard`,
> `analytics_get_correlation_matrix`, `analytics_get_parameter_insights`,
> `analytics_get_example_insights`) land in a follow-up wave. If a tool is not yet
> registered on the connected MCP server, do not fabricate its output: surface the
> brief's recommended drilldown as a portal deep-link instead (see *Fallback*), and tell
> the user the inline drilldown is coming.

## Tools

Call tools by name through the connected `traigent-analytics` MCP server. Treat every
field below as the tool's contract, not as a value to invent. If a field is absent in the
response, say so rather than guessing.

### `analytics_get_run_decision_brief` (keystone — call first)

```text
analytics_get_run_decision_brief(
    project_id = "<explicit project id>",   # required; never assume a global 'latest'
    run_id     = "<explicit run id>",       # required
    intent     = "deploy" | "diagnose" | "compare" | "reduce_cost" | "explore",
)
```

Returns a compact, already-computed decision brief. The skill renders it; it does not
re-derive it.

```json
{
  "headline": "string — one-sentence verdict in plain language",
  "confidence": "high | medium | low",
  "confidence_reason": "string — why (e.g. trial count, score separation, variance)",
  "signal": "clean_winner | expensive_winner | dominated_winner | low_trials | one_knob_dominates | flat | noisy_examples | cost_blowup",
  "evidence": ["string", "..."],          // 2-4 plain-language bullets, no raw per-example values
  "recommended_action": {
    "action": "string — the single next step",
    "drilldown_tool": "string | null",    // which drilldown deepens this, if any
    "skill": "string | null"              // a companion skill to hand off to, if any
  },
  "metrics_summary": {                      // headline numbers only; full data is in drilldowns
    "best_score": "number | null",
    "trial_count": "number",
    "total_cost": "number | null"
  },
  "portal_deeplink": "string — web URL to the run in the portal"
}
```

`confidence` and `confidence_reason` are honest, server-computed labels. Never upgrade a
`low`/`medium` confidence to a stronger claim when narrating. `intent` biases which signal
and action the brief leads with (e.g. `reduce_cost` foregrounds the Pareto knee), but the
brief is always internally consistent — surface what it returns.

### `analytics_render_chart` (call when geometry matters)

```text
analytics_render_chart(
    project_id = "<project id>",
    run_id     = "<run id>",
    chart      = "pareto" | "correlation_heatmap" | "leaderboard" | "parameter_importance" | "convergence",
    intent     = "<same intent as the brief, optional>",
)
```

Returns a rendered image the skill shows **inline**. Use it when a trade-off or a
correlation structure is easier to see than to list — primarily `pareto` (accuracy vs.
cost knee) and `correlation_heatmap`. Lead with the brief's words first; add the chart
only when the signal calls for geometry or the user asks to see it.

```json
{
  "chart": "pareto",
  "image": { "format": "png", "data_ref": "<server-provided image reference>" },
  "caption": "string — server-written, honest caption for the figure",
  "notes": ["string", "..."]
}
```

### Drilldown tools (follow-up wave — reference by name now)

Each drilldown deepens exactly one signal. Pull at most one per turn, and only when a
signal triggers it or the user asks. All are scoped to a single run by `(project_id,
run_id)` and return already-computed, content-safe summaries.

| Tool | Deepens | Returns (shape only) |
|---|---|---|
| `analytics_get_single_run_pareto` | `expensive_winner` | `{ "frontier": [{ "config_label", "score", "cost" }], "knee": { "config_label", "score", "cost" }, "dominated_count" }` |
| `analytics_get_run_leaderboard` | comparing configs | `{ "rows": [{ "rank", "config_label", "score", "cost", "trials" }], "objective" }` |
| `analytics_get_correlation_matrix` | which knobs move together | `{ "params": ["..."], "matrix": [[number]], "objective_correlations": { "param": number } }` |
| `analytics_get_parameter_insights` | `one_knob_dominates` / `flat` | `{ "ranked": [{ "param", "effect", "label", "best_value" }], "method_note" }` |
| `analytics_get_example_insights` | `noisy_examples` | `{ "summary": { "scored", "n_examples", "algorithm_version" }, "weak_example_ids": ["..."] }` |

`analytics_get_example_insights` returns **non-signal scoring metadata only** — example
ids, counts, algorithm version, scored flags. It never exposes proprietary difficulty,
informativeness, ambiguity, or signal-vector values. Do not ask for, infer, or print such
values; they are not in the contract.

## WHAT TO SHOW WHEN — the decision table

The brief's `signal` field already encodes this mapping; the table is the human-readable
contract so the skill can explain *why* it is surfacing a given drilldown and *what to do
next*. Lead with the headline and the single recommended action; pull the "first surface"
only when the signal fires or the user asks.

| `signal` | What it means | First surface (only if triggered / asked) | Recommended next action |
|---|---|---|---|
| `clean_winner` | One config clearly best; score separation is real and confidence is not low | (none — headline is enough) | Deploy the winner; gate it with `traigent-ci-safety-gate` before promotion |
| `expensive_winner` | Best config costs > ~1.5× a near-tied cheaper config for a small gain | `analytics_render_chart(chart="pareto")` + `analytics_get_single_run_pareto` | Pick the Pareto **knee**, not the raw max; confirm the cheaper config on a holdout |
| `dominated_winner` | The "winner" is beaten on both score and cost by another config | `analytics_get_run_leaderboard` | Reject it; promote the dominating config instead |
| `low_trials` | Fewer than ~10 successful trials — separation may be noise | (none — state low confidence) | Run more trials before deciding (`traigent-run-optimization`); treat current ranking as provisional |
| `one_knob_dominates` | A single knob explains most objective variance | `analytics_get_parameter_insights` + `analytics_render_chart(chart="parameter_importance")` | Narrow that knob's range; add structural knobs with `traigent-configuration-space` / `traigent-composite-knobs` |
| `flat` | Scores barely move across the whole space | `analytics_get_parameter_insights` (to confirm nothing bites) | Change the space or the data: harder examples via `traigent-curate-dataset`, or new knobs |
| `noisy_examples` | The same examples fail across otherwise-good configs | `analytics_get_example_insights` | Fix the dataset/evaluator: feed weak ids into guided optimization, audit with `traigent-evaluator-audit` |
| `cost_blowup` | Cost or latency is the blocker, not score | `analytics_render_chart(chart="pareto")` | Add a guardrail/budget; cap cost with `traigent-run-optimization`, gate with `traigent-ci-safety-gate` |

This mapping mirrors the symptom→action table in `traigent-iterate`; that skill owns the
*deeper* "what experiment next" decision once the terminal brief has named the signal.

## Fallback when a tool is unavailable

If the connected MCP server does not expose a needed tool yet:

1. Show the brief's `portal_deeplink` so the user can open the run in the portal.
2. Name the drilldown the brief recommends and say it will be available inline once the
   follow-up tools land.
3. Never print invented numbers, charts, or rankings in place of a real tool response.

The deep-link is the portal's own run URL (web UI), e.g.
`https://portal.traigent.ai/p/<project_id>/runs/<run_id>` — it is a navigation fallback,
not an API call the skill makes.
