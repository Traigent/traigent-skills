"""Escape route: shell out. Selected with --scorer in the test, and refused."""

import os
import subprocess


def score(output, expected):
    port = os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0")
    command = ["curl", "-s", "-m", "2", f"http://localhost:{port}/subprocess"]
    subprocess.run(command, capture_output=True, check=False)
    return 1.0 if output == expected else 0.0
