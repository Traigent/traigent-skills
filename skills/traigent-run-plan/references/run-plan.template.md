# Traigent Run Plan Record

Use this file to record a plan returned by the Traigent service and the user's
confirmations. It is a capture format, not a source of recommended settings.

## Context Sent To Traigent

- Task:
- Agent entrypoint:
- Dataset size:
- Holdout split:
- Objectives:
- Budget:
- Prior run id or portal context:
- User-approved egress notes:

## Service Payload

Paste or summarize the returned payload. Keep the service fields intact.

- `schema_version`:
- `phase`:
- `plan.objectives`:
- `plan.models`:
- `plan.knobs`:
- `plan.algorithm`:
- `plan.max_trials`:
- `plan.cost_limit_usd`:
- `plan.offline`:
- `steps`:
- `evidence_level`:
- `caveat`:
- `advisory`:

## User Confirmations

For each returned option, record one of: approved as returned, adjusted by user,
or refreshed from Traigent.

| Option | Service value | User decision | Notes |
|---|---|---|---|
| Objectives |  |  |  |
| Models |  |  |  |
| Knobs |  |  |  |
| Algorithm |  |  |  |
| Max trials |  |  |  |
| Cost limit |  |  |  |
| Offline selector |  |  |  |
| Returned steps |  |  |  |

## Mock Dry-Run

- Mock command or SDK entrypoint:
- What executed:
- What was intentionally not executed:
- Wiring result:
- Estimated real-run cost if available:
- Blockers:

## Real Run Approval

- Explicit user go:
- Cost cap confirmed:
- Returned steps executed:
- Run id:
- Portal link:

## Carry Forward

After the run, paste the server next-step payload from `traigent-next-run` or link
to its record. Do not add local next-step decisions here.
