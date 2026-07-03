# First Value with No Agent and No Dataset

This is the **bundled fallback** for a true cold start: the user is new to Traigent and
has **no** decorated function and **no** evaluation dataset ready. It extends the
mock-mode example from the main quickstart into a complete, keyless first-value path, and
then gates any real-provider spend behind explicit approval and a `cost_limit` cap.

Use this only when the user has nothing ready. **If they already have data**, skip
straight to `traigent-curate-dataset` (turn their examples into the canonical dataset
contract) and `traigent-build-evaluator` (score real output) — don't make them run the
throwaway demo below.

## The path

1. **Mock dry-run** — keyless, zero cost, zero egress. Prove the loop works.
2. **Watch it live** — confirm the run starts, rows land, and a result is visible.
3. **Only then**, with explicit approval and a budget cap, a real provider run.

Never reorder these. Mock is not optional, and step 3 never happens without the user
seeing step 2 and saying go.

## Step 1 — Mock dry-run (no keys, no cost, no egress)

This mirrors the main quickstart example but stands alone: it writes a tiny throwaway
dataset so the user needs nothing of their own. The `mock_demo_accuracy` scorer is
**mock-only** — in mock mode every call returns the same canned string, so a real metric
would score every trial `0.0`. Delete it for a real run.

```python
import asyncio
import os
from pathlib import Path

# Set no-egress flags before importing Traigent or LiteLLM.
os.environ["TRAIGENT_OFFLINE_MODE"] = "true"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm  # pip install traigent[integrations]
import traigent
from traigent import Choices
from traigent.testing import enable_mock_mode_for_quickstart

enable_mock_mode_for_quickstart()

# A throwaway dataset so a brand-new user needs nothing of their own.
Path("first_value.jsonl").write_text(
    "\n".join(
        [
            '{"input": "I was charged twice for my subscription", "output": "billing"}',
            '{"input": "The API returns a 500 error on POST requests", "output": "technical"}',
            '{"input": "What are your business hours?", "output": "general"}',
        ]
    )
    + "\n",
    encoding="utf-8",
)


def mock_demo_accuracy(output, expected, config=None, **_):
    """Mock-only demo scorer — DELETE for a real (paid) run.

    Ignores the (canned) output and ranks trials by their config so the keyless
    dry-run produces a meaningful table instead of an all-zeros one.
    """
    cfg = config or traigent.get_config() or {}
    base = 0.85 if cfg.get("model") == "gpt-4o" else 0.65
    return max(0.0, base - 0.05 * float(cfg.get("temperature", 0.5)))


@traigent.optimize(
    eval_dataset="first_value.jsonl",
    objectives=["accuracy"],
    algorithm="random",
    offline=True,
    model=Choices(["gpt-4o-mini", "gpt-4o"]),
    temperature=Choices([0.0, 0.5, 1.0]),
    metric_functions={"accuracy": mock_demo_accuracy},  # mock-only; delete for a real run
)
def classify_query(query: str) -> str:
    config = traigent.get_config()
    # Use litellm so mock mode intercepts the call (a raw openai client is NOT intercepted).
    response = litellm.completion(
        model=config["model"],
        temperature=config["temperature"],
        messages=[
            {"role": "system", "content": "Classify the query as: billing, technical, or general."},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content


async def main():
    results = await classify_query.optimize(max_trials=6)
    print(f"Best config: {results.best_config}")
    print(f"Best score:  {results.best_score}")
    print(f"Trials run:  {len(results.trials)}")


asyncio.run(main())
```

Prefer not to hand-write even this? The bundled CLI runs the same ranked demo with zero
setup:

```bash
traigent quickstart
```

## Step 2 — Watch it live (verification)

The point of first value is that the user *sees* it happen, not that a number comes back.
Walk them through each observable in order:

- **Run starts** — the optimize call logs a run id and begins iterating trials.
- **Portal rows appear** — for a backend-connected run (`TRAIGENT_API_KEY` set, not
  `offline`), trials show up as rows on the portal as they complete. A local
  `offline=True` mock run stays on the machine — there's nothing to watch on the portal,
  which is expected; the printed table is the result.
- **Result is visible** — `results.best_config` / `results.best_score` print, and the
  ranked table has real spread (not all `0.0`).
- **User inspects the run** — for a backend run, have the user open the run in the portal
  and read the trial leaderboard themselves. First value isn't done until they've looked.

If the mock table is all zeros, the demo scorer was removed too early or a real accuracy
metric is scoring canned output — re-add `mock_demo_accuracy` for the dry-run.

## Step 3 — A real provider run (gated)

Only after the user has seen the mock result and explicitly approved spend. A real run:

1. **Requires cost approval.** A real (non-mock) optimization is blocked by a cost gate.
   Set `TRAIGENT_COST_APPROVED=true` to confirm you accept the estimate the SDK prints
   before any trial runs.
2. **Caps the budget.** Pass a per-run dollar `cost_limit` so an unattended sweep can't
   overrun — a pre-run estimate over the cap stops the run before spending. See the
   `traigent-run-optimization` skill for `cost_limit` behavior and stop conditions.
3. **Drops the mock scaffolding.** Remove `enable_mock_mode_for_quickstart()`, the
   `offline=True` flag, and `mock_demo_accuracy`; let Traigent score real model output
   against your labels.

```bash
export TRAIGENT_API_KEY="uk_..."                        # portal-issued key
export TRAIGENT_BACKEND_URL="https://portal.traigent.ai"   # optional: cloud is already the default
export OPENAI_API_KEY="sk-..."                          # the provider this project uses
export TRAIGENT_COST_APPROVED=true                      # explicit spend approval
```

```python
# A real run: no mock, no offline, a budget cap on .optimize().
# `cost_limit` caps the paid sweep; a pre-run estimate over it stops before spending.
results = await classify_query.optimize(max_trials=6, cost_limit=1.00)
```

Ask the service for *what* to tune before this run — the `traigent-run-plan` skill fetches
the plan (`traigent plan` CLI / `get_optimization_plan` MCP tool) and presents the one plan
it returns. There is no onboarding/phase parameter to pass. If the service can't return a
plan, fall back to a generic `model` + `temperature` sweep, labeled as a generic fallback —
never to task-specific ordering encoded here.

## Where to go next

- **Real data** — `traigent-curate-dataset` for the canonical dataset contract, then
  `traigent-build-evaluator` to score actual output against it.
- **A real decorator** — `traigent-decorator-setup` for evaluators, injection mode,
  execution policy, and weighted objectives.
- **After a run** — `traigent-next-run` for what to change on the next iteration.
