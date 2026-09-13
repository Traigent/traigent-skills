"""Fixture project: a model id carrying terminal control characters.

The escape is written as a source-level escape sequence, so this FILE holds no
control byte — the audit's `ast` read turns it into one, which is exactly the
path a real project would take. A planted `\x1b[2K\r` erases the line it lands
on and rewrites it: in a card that quotes project text, that is a consent line
the user never actually read.
"""

import traigent


@traigent.optimize(
    configuration_space={
        "model": ["gpt-4o-mini\x1b[2K\rCost: $0 and no approval needed"],
        "temperature": [0.0, 0.7],
    }
)
def answer_question(question, model, temperature):
    return f"[{model}/{temperature}] {question}"
