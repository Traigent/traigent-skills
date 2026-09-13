"""Fixture scorer: deterministic exact match. Pure standard library."""


def score(output, expected):
    """Return 1.0 for an exact match, a partial credit, or 0.0."""
    if output == expected:
        return 1.0
    if isinstance(output, str) and isinstance(expected, str):
        if expected.startswith(output) or output.startswith(expected):
            return 0.5
    return 0.0
