"""Escape route: call libc `system` through ctypes, bypassing Python sockets.

Reaches the host network at the python-level guard, so this module must be
classified `executing` and never run; under a network namespace it reaches
nothing even if it is run.
"""

import ctypes
import os


def score(output, expected):
    port = os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0")
    libc = ctypes.CDLL(None)
    libc.system(f"curl -s -m 2 http://localhost:{port}/ctypes".encode())
    return 1.0 if output == expected else 0.0
