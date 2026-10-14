"""Callback ordering observed on the unmodified verifier."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import equivalence_result as mod  # noqa: E402


def observed():
    trace = []

    class Ids(list):
        def __iter__(self):
            trace.append("ids.iter")
            return super().__iter__()

        def __len__(self):
            trace.append("ids.len")
            return super().__len__()

    class Response(dict):
        def get(self, key, default=None):
            trace.append("response.get:" + key)
            return super().get(key, default)

    class Check(dict):
        def get(self, key, default=None):
            trace.append("check.get:" + key)
            return super().get(key, default)

    ids = Ids(["a", "b"])
    response = Response(protocol="p3b-v1", run_id="r", selection_rule="sel-v1",
                        example_ids=ids, count=2, digest=mod.selection_digest(["a", "b"]))
    check = Check({key: response[key] for key in ("protocol", "run_id", "selection_rule", "count", "digest")})
    return trace, response, check


def test_exact_callback_order():
    trace, response, check = observed()
    assert mod.verify_selection(response, check) == ["a", "b"]
    assert trace == [
        "response.get:protocol", "response.get:selection_rule", "response.get:example_ids",
        "ids.iter", "response.get:count", "ids.len", "response.get:digest", "ids.iter", "ids.len",
        "check.get:protocol", "response.get:protocol", "check.get:run_id", "response.get:run_id",
        "check.get:selection_rule", "response.get:selection_rule", "check.get:count", "response.get:count",
        "check.get:digest", "response.get:digest", "ids.iter", "ids.len",
    ]


def test_mutating_check_get_is_observed_by_final_copy():
    response = dict(protocol="p3b-v1", selection_rule="sel-v1", run_id="r", count=1,
                    example_ids=["a"], digest=mod.selection_digest(["a"]))

    class Check(dict):
        def get(self, key, default=None):
            if key == "digest":
                response["example_ids"].append("late")
            return response.get(key, default)

    result = mod.verify_selection(response, Check())
    assert result == ["a", "late"]
    assert result is not response["example_ids"]


def test_digest_get_mutation_occurs_before_digest_computation():
    class Response(dict):
        def get(self, key, default=None):
            if key == "digest":
                self["example_ids"].append("late")
                return mod.selection_digest(self["example_ids"])
            return super().get(key, default)

    response = Response(protocol="p3b-v1", selection_rule="sel-v1", count=1, example_ids=["a"])
    assert mod.verify_selection(response) == ["a", "late"]


def test_len_error_occurs_after_iteration_and_count_get():
    trace = []

    class Ids(list):
        def __iter__(self):
            trace.append("iter")
            return super().__iter__()

        def __len__(self):
            trace.append("len")
            raise RuntimeError("length callback failed")

    class Response(dict):
        def get(self, key, default=None):
            trace.append(key)
            return super().get(key, default)

    response = Response(protocol="p3b-v1", selection_rule="sel-v1", example_ids=Ids(["a"]), count=1)
    with pytest.raises(RuntimeError, match="^length callback failed$"):
        mod.verify_selection(response)
    assert trace == ["protocol", "selection_rule", "example_ids", "iter", "count", "len"]
