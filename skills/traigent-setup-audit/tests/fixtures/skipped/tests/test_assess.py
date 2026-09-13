"""Fixture test module: a `score*` name inside a test file is not a scorer."""


def scorecards(tmp_path_factory):
    return {"variant": tmp_path_factory}
