# Traigent Run Plan Thin Client: text2SQL Example

Use this reference when the user wants a first run with the bundled text2SQL
example. The point is to exercise the same service-backed loop the user's own
agent will use.

## Context To Gather

- Task: bundled text2SQL example.
- Dataset size and holdout: read from the example setup or ask the user to
  confirm the installed fixture.
- Objectives: ask the user which objectives matter for the demo.
- Budget: ask for the maximum spend before any real run.
- Egress: confirm whether the user permits sending a short summary to Traigent.

## Fetch The Plan

Call the Traigent service with that context using `traigent plan` or the MCP tool
`get_optimization_plan`. The service returns the objectives, models, knobs,
algorithm, trial budget, cost cap, offline setting, and executable steps.

Do not use this reference to choose example models, knobs, or counts. If the
returned plan is missing a needed field, re-query Traigent or stop for user input.

## Present And Confirm

Show each returned option group to the user:

- objectives,
- models,
- knobs,
- algorithm,
- max trials,
- cost limit,
- offline setting,
- returned steps,
- `phase`, `evidence_level`, `caveat`, and `advisory`.

Record confirmations in `run-plan.template.md`.

## Execute

Run the returned mock dry-run step first and stop. Launch the real run only after
the user explicitly says to go and the service plan's cost cap is set.

After completion, pass the run id and portal link to `traigent-next-run`.
