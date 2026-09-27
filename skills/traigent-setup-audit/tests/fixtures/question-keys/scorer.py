"""Fixture scorer: deterministic exact match. Pure standard library."""


def score(output, expected):
    return 1.0 if output.strip() == expected.strip() else 0.0
