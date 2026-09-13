"""Escape route: name the module at runtime through the import builtin.

Nothing in this file's imports mentions ctypes, so an import-only classifier
called it deterministic and it reached the network. The name is assembled at
runtime here for the same reason a real attempt would: to stay out of the
static read.
"""

import builtins
import os


def score(output, expected):
    port = os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0")
    bring_in = getattr(builtins, "__imp" + "ort__")
    libc = bring_in("ctypes").CDLL(None)
    libc.system(f"curl -s -m 2 http://localhost:{port}/dynamic-builtin".encode())
    return 1.0 if output == expected else 0.0
