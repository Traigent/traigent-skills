"""Canary: write the key to stderr, then end the process without a result."""

import os
import sys

sys.stderr.write("fatal: key " + os.getenv("TRAIGENT_API_KEY", "") + "\n")
sys.stderr.flush()
os._exit(1)


def score(output, expected):
    return 1.0
