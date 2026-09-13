"""Fixture scorer: the one real scorer in this tree. Pure standard library."""


def score(output, expected):
    return 1.0 if output == expected else 0.0


def _private_helper(rows, expected):
    """Private name: matches the search by shape, is not a scorer."""
    return len(rows) == expected
