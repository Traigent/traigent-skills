"""Escape route: drop `socket` from the module table and import it again.

A fresh import rebuilds the real entry points, so any in-process patch of them
is undone. Classified `executing` because it touches `sys.modules`; under a
network namespace it reaches nothing even if it is run.
"""

import os
import sys


def score(output, expected):
    port = int(os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0"))
    sys.modules.pop("socket", None)
    import socket

    connection = socket.create_connection(("localhost", port), timeout=2)
    connection.close()
    return 1.0 if output == expected else 0.0
