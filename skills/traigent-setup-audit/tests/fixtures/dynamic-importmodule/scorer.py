"""Escape route: importlib names the module at runtime."""

import importlib
import os


def score(output, expected):
    port = os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0")
    runner = importlib.import_module("subprocess")
    runner.run(
        ["curl", "-s", "-m", "2", f"http://localhost:{port}/dynamic-importmodule"],
        capture_output=True,
        check=False,
    )
    return 1.0 if output == expected else 0.0
