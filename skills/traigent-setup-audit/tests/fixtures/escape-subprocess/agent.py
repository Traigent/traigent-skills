"""Fixture agent for a network-escape probe. Parsed with `ast`, never imported."""

import traigent


@traigent.optimize(configuration_space={"model": ["gpt-4o-mini"]})
def answer_question(question, model):
    return f"[{model}] {question}"
