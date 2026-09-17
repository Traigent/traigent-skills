"""Fixture project: a customer's own agent after a completed guided first run.

Parsed with `ast` by the audit, never imported. The first run left its
walkthrough artifacts under `traigent-runs/` and the two-file dataset layout
(`eval/tuning.jsonl` + `eval/holdout.jsonl`) it writes.
"""

import traigent


@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "claude-haiku-4-5-20251001"],
        "temperature": [0.0, 0.7],
    }
)
def answer_question(question, model, temperature):
    """Both declared knobs are parameters this body reads."""
    return f"[{model}/{temperature}] {question}"
