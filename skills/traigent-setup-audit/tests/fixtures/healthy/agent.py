"""Fixture project: a wired agent. Parsed with `ast` by the audit, never imported.

The `traigent` import below is text the audit reads; the tests do not execute
this module, so no SDK install is needed to run them.
"""

import traigent


@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini", "claude-haiku-4-5-20251001"],
        "temperature": [0.0, 0.7],
        "top_k": [1, 3],
    }
)
def answer_question(question, model, temperature, top_k):
    """Every declared knob is a parameter this body reads."""
    prefix = f"[{model}/{temperature}/{top_k}]"
    return f"{prefix} {question}"
