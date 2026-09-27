"""Fixture project: rows keyed `question`/`answer`. Parsed with `ast`, never imported."""

import traigent


@traigent.optimize(
    configuration_space={"model": ["gpt-4o-mini", "gpt-4o"], "temperature": [0.0, 0.7]}
)
def answer(question, model="gpt-4o-mini", temperature=0.0):
    return f"{model}:{temperature}:{question}"
