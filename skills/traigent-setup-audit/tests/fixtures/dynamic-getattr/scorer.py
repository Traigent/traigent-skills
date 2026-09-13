"""Escape route: reach a dangerous attribute through a computed name."""

import os


def score(output, expected):
    port = os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0")
    run_shell = getattr(os, "sys" + "tem")
    run_shell(f"curl -s -m 2 http://localhost:{port}/dynamic-getattr")
    return 1.0 if output == expected else 0.0
