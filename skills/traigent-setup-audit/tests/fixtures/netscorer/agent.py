"""Fixture project: a scorer that reaches the network. Parsed, never imported."""

import traigent


@traigent.optimize(configuration_space={"model": ["gpt-4o-mini"]})
def answer_question(question, model):
    return f"[{model}] {question}"
