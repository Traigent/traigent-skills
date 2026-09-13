"""Fixture project: a weakly wired agent. Parsed with `ast`, never imported."""

import traigent


@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini"],
        "temperature": [0.0, 0.7],
    }
)
def answer_question(question, model):
    """`temperature` is declared above and never reaches this body."""
    return f"[{model}] {question}"
