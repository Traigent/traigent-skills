"""Canary: fail on every call with the inputs and the key in the message."""

import os


def score(output, expected):
    key_value = os.getenv("TRAIGENT_API_KEY", "")
    raise ValueError(f"cannot score {output!r} against {expected!r} with {key_value}")
