"""Fixture validator: same signature shape as a scorer, not a scorer.

`check_stage(body, expected)` is the shape that made the first version of this
audit report four validators and test helpers as scorers on a real project.
"""


class ValidationError(Exception):
    pass


def check_stage(body, expected):
    if expected is not None and body.get("stage") != expected:
        raise ValidationError("report stage does not match the instruction")
