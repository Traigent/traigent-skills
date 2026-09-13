"""Canary: fail at import with the key in the exception message.

The audit must report the exception TYPE and a file:line, never the message.
`score` is defined first so the static search still finds a scorer to probe;
the module then raises before the probe can reach it.
"""

import os


def score(output, expected):
    return 1.0 if output == expected else 0.0


key_value = os.getenv("TRAIGENT_API_KEY", "")
raise RuntimeError("misconfigured key " + key_value)
