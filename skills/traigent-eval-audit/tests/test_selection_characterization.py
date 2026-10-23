"""Frozen public behavior of selection verification before helper extraction."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "equivalence_result.py"
sys.path.insert(0, str(SCRIPT.parent))
import equivalence_result as mod  # noqa: E402

CHECK_KEYS = ("protocol", "run_id", "selection_rule", "count", "digest")


def selection(ids=None):
    ids = ["z", "a"] if ids is None else ids
    return {"protocol": "p3b-v1", "run_id": "run-1", "selection_rule": "sel-v1",
            "example_ids": ids, "count": len(ids), "digest": mod.selection_digest(ids)}


@pytest.mark.parametrize("value", [None, [], (), "x", 7])
def test_object_gate(value):
    with pytest.raises(ValueError) as error:
        mod.verify_selection(value)
    assert str(error.value) == "selection must be a JSON object"


@pytest.mark.parametrize("updates,message", [
    ({"protocol": None, "selection_rule": None, "example_ids": None}, "unknown protocol"),
    ({"selection_rule": None, "example_ids": None}, "unknown selection rule"),
    ({"example_ids": None, "count": None, "digest": None}, "example_ids must be a list of strings"),
    ({"count": None, "digest": None}, "count does not match the number of example_ids"),
    ({"digest": None}, "digest does not match the example_ids"),
])
def test_response_validation_order(updates, message):
    response = selection()
    response.update(updates)
    with pytest.raises(ValueError) as error:
        mod.verify_selection(response, {})
    assert str(error.value) == message


@pytest.mark.parametrize("ids", ["a", ("a",), {}, [1], [True], [None], ["a", []]])
def test_ids_type_and_members(ids):
    response = selection()
    response["example_ids"] = ids
    with pytest.raises(ValueError, match="^example_ids must be a list of strings$"):
        mod.verify_selection(response)


@pytest.mark.parametrize("count", [True, False, 2.0, "2", None, -1, 0, 1, 3])
def test_count_type_bool_and_length(count):
    response = selection()
    response["count"] = count
    with pytest.raises(ValueError, match="^count does not match the number of example_ids$"):
        mod.verify_selection(response)


@pytest.mark.parametrize("ids,count", [(["x"], True), ([], False)])
def test_bool_count_rejected_even_when_equal(ids, count):
    response = selection(ids)
    response["count"] = count
    with pytest.raises(ValueError, match="^count does not match the number of example_ids$"):
        mod.verify_selection(response)


@pytest.mark.parametrize("digest", [None, 7, "", "SHA256:" + "0" * 64, "sha256:" + "0" * 64])
def test_digest_rejection(digest):
    response = selection()
    response["digest"] = digest
    with pytest.raises(ValueError, match="^digest does not match the example_ids$"):
        mod.verify_selection(response)


@pytest.mark.parametrize("first", range(len(CHECK_KEYS)))
def test_check_fields_are_checked_in_order(first):
    response = selection()
    check = {key: response[key] for key in CHECK_KEYS}
    for key in CHECK_KEYS[first:]:
        check[key] = "wrong"
    with pytest.raises(ValueError) as error:
        mod.verify_selection(response, check)
    assert str(error.value) == f"{CHECK_KEYS[first]} differs from the instruction's check block"


@pytest.mark.parametrize("check", [[], (), "bad", 7, True])
def test_non_mapping_check_exposes_attribute_error(check):
    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        mod.verify_selection(selection(), check)


def test_missing_keys_unknown_keys_and_missing_run_id():
    response = selection()
    response.pop("run_id")
    response["unknown"] = {"accepted": True}
    check = {key: response[key] for key in CHECK_KEYS if key != "run_id"}
    check["unknown"] = "different and ignored"
    assert mod.verify_selection(response, check) == ["z", "a"]
    for key, message in [("protocol", "unknown protocol"), ("selection_rule", "unknown selection rule"),
                         ("example_ids", "example_ids must be a list of strings"),
                         ("count", "count does not match the number of example_ids"),
                         ("digest", "digest does not match the example_ids")]:
        malformed = selection()
        del malformed[key]
        with pytest.raises(ValueError) as error:
            mod.verify_selection(malformed)
        assert str(error.value) == message


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


class IntSubclass(int):
    pass


class StrSubclass(str):
    pass


def test_subclasses_duplicates_empty_strings_and_copy_identity():
    ids = ListSubclass([StrSubclass(""), StrSubclass("a"), StrSubclass("a")])
    response = DictSubclass(selection(ids))
    response["count"] = IntSubclass(3)
    response["protocol"] = StrSubclass("p3b-v1")
    response["selection_rule"] = StrSubclass("sel-v1")
    check = DictSubclass({key: response[key] for key in CHECK_KEYS})
    before = copy.deepcopy((response, check))
    result = mod.verify_selection(response, check)
    assert type(result) is list
    assert result == ids
    assert result is not ids
    assert result[0] is ids[0]
    assert (response, check) == before
    result.append("new")
    assert len(ids) == 3


def test_custom_get_iteration_and_errors_are_not_hidden():
    class RaisingDict(dict):
        def get(self, key, default=None):
            raise RuntimeError("custom get failed")

    class RaisingList(list):
        def __iter__(self):
            raise RuntimeError("custom iteration failed")

    with pytest.raises(RuntimeError, match="^custom get failed$"):
        mod.verify_selection(RaisingDict())
    response = selection()
    response["example_ids"] = RaisingList(["a"])
    with pytest.raises(RuntimeError, match="^custom iteration failed$"):
        mod.verify_selection(response)


def test_digest_uses_ordered_compact_ascii_json():
    ids = ["é", "a", "a"]
    expected = "sha256:" + hashlib.sha256(b'["\\u00e9","a","a"]').hexdigest()
    assert mod.selection_digest(ids) == expected
    assert mod.verify_selection(selection(ids)) == ids
    assert mod.verify_selection(selection([])) == []


@pytest.mark.parametrize("bad,message", [
    (None, None), ({"count": True}, "count does not match the number of example_ids"),
    ({"digest": "bad"}, "digest does not match the example_ids"),
])
def test_cli_selection_good_and_refusal(tmp_path, bad, message):
    response = selection()
    check = {key: response[key] for key in CHECK_KEYS}
    if bad:
        response.update(bad)
    selection_path, check_path = tmp_path / "selection.json", tmp_path / "check.json"
    selection_path.write_text(json.dumps(response), encoding="utf-8")
    check_path.write_text(json.dumps(check), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCRIPT), "verify-selection", "--selection",
                                str(selection_path), "--check", str(check_path)],
                               capture_output=True, text=True)
    assert completed.stderr == ""
    if message:
        assert completed.returncode == 1
        assert json.loads(completed.stdout) == {"ok": False, "error": message}
    else:
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == {"ok": True, "count": 2, "example_ids": ["z", "a"]}
