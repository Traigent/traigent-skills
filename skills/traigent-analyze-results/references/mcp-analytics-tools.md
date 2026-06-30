# Terminal-First Analytics — MCP Tool Contract

This reference documents the `traigent-analytics` MCP server surface that the skill may
call for cloud/portal runs. The skill orchestrates and narrates; it must not compute
analytics, rank trials, fit Pareto frontiers, infer hidden fields, or run auth/tenant logic.

## Registered Tools

Use only these analytics tool names:

| Tool | Signature | Use |
|---|---|---|
| `analytics_get_run_decision_brief` | `(project_id, run_id, intent="iterate")` | Fetch the v0 decision payload for one run. Call first. |
| `analytics_get_run_report` | `(project_id, run_id)` | Fetch the backend analytics report payload for one run. |
| `analytics_get_project_overview` | `(project_id)` | Fetch the project-level optimization overview. |
| `analytics_compare_runs` | `(project_id, run_ids)` | Compare two or more runs. |
| `analytics_get_single_run_pareto` | `(project_id, run_id, x_measure="cost", y_measure="quality", request_count=1)` | Fetch one run's Pareto frontier (cost/quality trade-off). |
| `analytics_get_correlation_matrix` | `(project_id, run_id, method="pearson", min_sample=3)` | Fetch one run's measure/parameter correlations. |
| `analytics_get_run_leaderboard` | `(project_id, run_id, objective="weighted", weights=None, constraints=None, request_count=1, limit=50)` | Rank a run's configs by a weighted objective. |
| `analytics_get_parameter_insights` | `(project_id, run_id, target_measure="quality", min_trials=10, top_k=10)` | Parameter-importance insights for one run. |
| `analytics_get_example_insights` | `(project_id, run_id)` | Privacy-bounded example / dataset-quality insights (safe projection only — coarse counts, cohorts, redacted refs; never raw signals). |
| `analytics_render_chart` | `(payload, kind, output_path=None)` | Render an already-fetched payload. `kind` must be `run_pareto` or `run_correlations`. |

Do not call unlisted analytics tool names. If a tool response has `ok: false`, report the
failure at a high level and do not invent missing data.

## Decision Brief

Call this first:

```text
analytics_get_run_decision_brief(
    project_id = "<explicit project id>",
    run_id     = "<explicit run id>",
    intent     = "iterate" | "deploy" | "debug" | "report",
)
```

The MCP tool returns:

```json
{
  "ok": true,
  "decision_brief": {
    "run_id": "string",
    "project_id": "string",
    "intent": "iterate | deploy | debug | report",
    "headline": "string",
    "confidence": "low | medium | high",
    "recommended_action": {
      "kind": "string",
      "config_id": "string | null",
      "why": "string"
    },
    "evidence": [
      {"type": "string", "summary": "string"}
    ],
    "drilldowns": [
      {"label": "string", "tool": "string"}
    ],
    "warnings": ["string"]
  }
}
```

Narrate only the fields present in the decision-payload schema above. If a field is absent,
omit it; do not reference or invent fields that are not in the schema.

## Run Report, Overview, and Comparison

Use these registered read tools when the user asks for broader context:

```text
analytics_get_run_report(project_id = "<project id>", run_id = "<run id>")
analytics_get_project_overview(project_id = "<project id>")
analytics_compare_runs(project_id = "<project id>", run_ids = ["<run a>", "<run b>"])
```

They return `ok: true` plus one payload key named after the requested object:
`run_report`, `project_overview`, or `run_comparison`. Treat those payloads as backend-owned
open objects. Do not claim a field exists unless it is present.

Portal cohort/group views are not a substitute for `analytics_compare_runs`. A cohort is a
read-time portal/API convenience over source ids for runs sharing the same agent and canonical
dataset. It does not dedupe configurations by tuned variables, objectives, or config hashes, and it
does not turn multiple runs into one analytics run. For analytics, use one explicit `run_id` or pass
the exact `run_ids` to `analytics_compare_runs`.

## Chart Rendering

The render tool is local rendering only:

```text
analytics_render_chart(
    payload     = <backend-produced run_pareto or run_correlations object>,
    kind        = "run_pareto" | "run_correlations",
    output_path = "<png-or-svg-output-path>",
)
```

It does not fetch Pareto/correlation data and does not recompute analytics. Call it only when
you already have a backend-produced payload matching the selected `kind` — typically the
`run_pareto` payload from `analytics_get_single_run_pareto` or the `run_correlations` payload
from `analytics_get_correlation_matrix` (or one already present in a run-report response).

The success response is:

```json
{
  "ok": true,
  "kind": "run_pareto",
  "chart_path": "string"
}
```

## Single-Run Drilldowns

These single-run drilldowns are **registered** (SDK >= 0.18.0.dev0). Call them directly for a
focused view; pull at most one extra drilldown per turn, and only when the user asks or the
brief's `recommended_action` / `warnings` clearly call for it. Full signatures (all optional
params and defaults) are in the **Registered Tools** table above.

| Drilldown | Tool | Notes |
|---|---|---|
| Pareto frontier | `analytics_get_single_run_pareto` | Returns a `run_pareto` payload; pass it to `analytics_render_chart` with `kind="run_pareto"` to draw it. |
| Correlations | `analytics_get_correlation_matrix` | Returns a `run_correlations` payload; render with `kind="run_correlations"`. |
| Leaderboard | `analytics_get_run_leaderboard` | Ranked configs by weighted objective. |
| Parameter insights | `analytics_get_parameter_insights` | Parameter importance for one run. |
| Example insights | `analytics_get_example_insights` | Safe projection only — coarse counts, cohorts, redacted refs, templated recommendations. Never surface raw per-example signals. |

The portal deep-link remains a **fallback for interactive exploration** (hover / zoom / filter)
or for any view that has no registered tool — not because these tools are missing:

```text
https://portal.traigent.ai/p/<project_id>/runs/<run_id>
```

Treat every tool response as authoritative. If a tool returns `ok: false`, report the failure
at a high level. Never print invented rankings, example ids, chart captions, or field shapes.
