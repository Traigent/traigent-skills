"""Walkthrough substitute written by traigent-first-run — not the customer's agent."""

import traigent


@traigent.optimize(configuration_space={"model": ["gpt-4o-mini"], "style": ["terse", "full"]})
def walkthrough_answer(question, model, style):
    return f"[{model}/{style}] {question}"
