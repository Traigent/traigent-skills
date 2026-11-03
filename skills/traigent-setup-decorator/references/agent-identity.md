# Agent identity and run labels

Requires `traigent>=0.27.0`: `agent_name`, `run_title`, and `run_description` first shipped in
SDK 0.27.0. On older SDKs the identity key is `experiment_name` and there is no per-run label
argument; see "Naming" in `SKILL.md`.

`agent_name` is the stable identity of the agent. `experiment_name` is its **deprecated
alias**: it works, but if both are given `agent_name` wins and the SDK warns. The three
arguments are decorator arguments, not parameters of `.optimize()` / `.optimize_sync()`.

## Stable identity plus a per-run label

```python
import traigent


@traigent.optimize(
    agent_name="txt2sql_agent",                       # stable identity — same string every run
    run_title="Check best router model",              # what THIS run tests; may differ each run
    run_description="Hypothesis: the larger model wins on multi-join questions.",
    objectives=["accuracy"],
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"]},
)
def my_func(query: str) -> str:
    cfg = traigent.get_config()
    return prompt_model(query, model=cfg["model"])
```

`run_title` is trimmed to 512 characters and `run_description` to 4000. Both are labels only:
they never affect agent identity, cohorting, scoring, or recommendations, so change them
freely between runs.

## What forks the agent

Every one of these in `agent_name` creates a separate agent in the portal and fragments the
optimization history into one-run pieces. Put the same text in `run_title` instead.

```python
# contract: skip
agent_name="txt2sql v3 (claude, ACL>=0.8)"        # variant + config in the name
agent_name=f"txt2sql-{datetime.now():%Y%m%d}"     # date in the name
agent_name="check best router model"              # hypothesis in the name
```

## Resolution order

`agent_name`, then the deprecated `experiment_name`, then the `TRAIGENT_EXPERIMENT_NAME`
environment variable (read at access time), then a self-describing default derived from the
function name, objectives, and knobs. The derived default changes when a knob or objective is
added or removed, so set `agent_name` explicitly to keep one history across a changing search
space.
