"""Fixture scorer: not repeatable. Pure standard library."""

import random


def score(output, expected):
    """Mixes a match signal with an unseeded draw, so repeats disagree."""
    match = 1.0 if output == expected else 0.0
    return 0.5 * match + 0.5 * random.random()
