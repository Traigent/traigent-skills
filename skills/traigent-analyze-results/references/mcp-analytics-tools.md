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
| `analytics_render_chart` | `(payload, kind, output_path)` | Render an already-fetched payload. `kind` must be `run_pareto` or `run_correlations`. |

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

Narrate only fields that are present. The decision payload does not currently define
`signal`, `confidence_reason`, `metrics_summary`, `portal_deeplink`, `drilldown_tool`, or
companion-skill fields; do not reference those fields unless a future registered tool returns
them.

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
you already have a backend-produced payload matching the selected `kind`. If the run report
or a future registered tool does not include that payload, use the portal deep-link fallback.

The success response is:

```json
{
  "ok": true,
  "kind": "run_pareto",
  "chart_path": "string"
}
```

## Wave-2 Drilldowns

These single-run drilldowns are **NOT YET REGISTERED — do not call until the Wave-2 MCP tools
ship**:

| Drilldown | Do not call | Fallback |
|---|---|---|
| Pareto fetch | `analytics_get_single_run_pareto`, `run_pareto`, or similar | Open the portal Pareto view/deep-link. |
| Correlations fetch | `analytics_get_correlation_matrix`, `analytics_get_run_correlations`, or similar | Open the portal correlations view/deep-link. |
| Leaderboard | `analytics_get_run_leaderboard` or similar | Open the portal leaderboard view/deep-link. |
| Parameter insights | `analytics_get_parameter_insights` or similar | Open the portal parameter-insights view/deep-link. |
| Example insights | `analytics_get_example_insights` or similar | Open the portal example-insights view/deep-link. |

The fallback deep-link is navigation only, for example:

```text
https://portal.traigent.ai/p/<project_id>/runs/<run_id>
```

Never print invented rankings, example ids, chart captions, or field shapes for an
unregistered drilldown.
