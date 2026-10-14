"""Pin what the dataset reader, the next-step ladder and the Tier 2 report
reader, motivations and run mode return, print and write.

Each case below is run and its observation compared, ordering included, with
the recorded observation in ``pins/behaviour_pins.json``. The record was written
from the code before these functions were restructured, so any difference is a
behaviour change rather than a style change. Regenerate it only for an intended
change, and review the diff of the JSON file:

    python tests/test_behaviour_pins.py --write

``--dump PATH`` writes the observations without comparing, so two copies of
the scripts can be run over the same cases and their outputs diffed.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
PINS = TESTS_DIR / "pins" / "behaviour_pins.json"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_project as audit  # noqa: E402
import tier2_checks as tier2  # noqa: E402

# Never created on disk: `relative()` only does path arithmetic on it.
ROOT = Path("/nonexistent-pin-root")
PYVER = f"{sys.version_info[0]}.{sys.version_info[1]}"


# --------------------------------------------------------------------------
# serialising observations
# --------------------------------------------------------------------------


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        return f"<float {value!r}>"
    if isinstance(value, Path):
        return f"<path {value.as_posix()}>"
    return value


def _text(value: object) -> str:
    """Canonical, order-preserving text of one observation."""
    return json.dumps(_jsonable(value), ensure_ascii=False, allow_nan=False)


def _digest(value) -> dict:
    """A long value as its size, its first items and a hash of all of it: the
    hash still pins every item and its order, without a megabyte record."""
    text = _text(value)
    items = list(value.items()) if isinstance(value, dict) else list(value)
    return {
        "len": len(items),
        "head": _jsonable(items[:3]),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


INDEX_FIELDS = ("input_index", "holdout_input_index", "non_holdout_input_index",
                "untagged_input_index")


def _report(report: audit.DatasetReport) -> dict:
    observed = _jsonable(asdict(report))
    for name in INDEX_FIELDS:
        observed[name] = _digest(observed[name])
    for name, value in observed.items():
        if isinstance(value, list) and len(value) > 40:
            observed[name] = _digest(value)
    return observed


# --------------------------------------------------------------------------
# dataset rows
# --------------------------------------------------------------------------


def _q(i: int, prefix: str = "question") -> str:
    return f"{prefix} number {i} about topic {i * 7}"


def _rows(n: int, *, start: int = 0, prefix: str = "question", split=None,
          gold: object = "answer", key: str = "input", style: str = "metadata"):
    rows = []
    for i in range(start, start + n):
        row = {key: _q(i, prefix), "expected_output": gold}
        if split is not None:
            if style == "metadata":
                row["metadata"] = {"split": split}
            else:
                row["split"] = split
        rows.append(row)
    return rows


def _long(i: int, swap: str | None = None) -> str:
    words = [f"w{i}x{j}" for j in range(20)]
    if swap is not None:
        words[-1] = swap
    return " ".join(words)


def _dataset_cases() -> dict[str, tuple[str, audit.RawDataset]]:
    cases: dict[str, tuple[str, audit.RawDataset]] = {}

    def add(name, rows, *, file="eval/data.jsonl", notes=(), constants=None):
        cases[name] = (
            file,
            audit.RawDataset(rows=rows, notes=list(notes), constants=dict(constants or {})),
        )

    add("empty", [])
    add("five_rows", _rows(5))
    add("fifteen_rows", _rows(15))
    add("tagged_70", _rows(40, split="tune") + _rows(30, start=40, split="holdout"))
    add("tagged_short_holdout", _rows(40, split="tune") + _rows(10, start=40, split="holdout"))
    add("train_only_top_level_tags", _rows(35, split="  TRAIN ", style="top"))
    mixed = _rows(12)
    mixed += [{"question": _q(100 + i), "answer": "a"} for i in range(5)]
    mixed += [{"prompt": _q(200 + i), "label": "b"} for i in range(3)]
    mixed += [{"text": _q(300 + i), "output": "c"} for i in range(2)]
    mixed += [{"input_data": {"q": "x"}, "target": 1}]
    mixed += [{"messages": [{"role": "user", "content": "hi"}], "expected": "hello"}]
    mixed += [{"question": "loses to input", "input": "input wins", "label": "l",
               "output": "output wins"}]
    add("mixed_input_keys", mixed)
    add("question_keys_only", [{"question": _q(i), "answer": "a"} for i in range(31)])
    gold = _rows(20)
    gold += [{"input": _q(50 + i)} for i in range(3)]
    gold += [{"input": _q(60 + i), "expected_output": None} for i in range(2)]
    gold += [{"input": _q(70), "expected_output": float("nan")}]
    gold += [{"input": _q(71), "answer": float("inf")}, {"input": _q(72), "answer": float("-inf")}]
    gold += [{"input": _q(73), "target": ""}, {"input": _q(74), "label": "   "}]
    gold += [{"input": _q(75), "output": None, "label": "x"}]
    gold += [{"input": _q(76), "output": 0}, {"input": _q(77), "output": False},
             {"input": _q(78), "output": []}]
    add("gold_kinds", gold)
    add(
        "constants_and_notes",
        _rows(32),
        notes=["2 line(s) were not valid JSON and were skipped"],
        constants={"NaN": 2, "-Infinity": 1, "Infinity": 1},
    )
    dups = []
    for i in range(25):
        for j in range(7):
            text = f"Hello, World {i}!" if j % 2 else f"hello   world {i}"
            dups.append({"input": text, "expected_output": f"g{j}"})
    add("exact_duplicates_over_caps", dups)
    near = []
    for i in range(16):
        near.append({"input": _long(i), "expected_output": "a"})
        near.append({"input": _long(i, swap=f"other{i}"), "expected_output": "a"})
    near.append({"input": _long(99), "expected_output": "a"})
    near.append({"input": _long(99), "expected_output": "a"})
    add("near_duplicates", near)
    big = [{"input": f"cycled input {i % 3}", "expected_output": "x"} for i in range(5001)]
    add("over_near_duplicate_limit", big)
    add("labels_imbalanced",
        [{"input": _q(i), "label": "yes" if i < 22 else "no"} for i in range(25)])
    add("labels_balanced",
        [{"input": _q(i), "label": "yes" if i % 2 else "no"} for i in range(24)])
    add("labels_many", [{"input": _q(i), "label": f"l{i % 11}"} for i in range(25)])
    add("labels_nineteen", [{"input": _q(i), "label": "yes"} for i in range(19)])
    typed = [1, True, 1.0, "1", 2, "two"]
    add("labels_mixed_types",
        [{"input": _q(i), "label": typed[i % len(typed)]} for i in range(22)])
    add("non_scalar_expected",
        [{"input": _q(i), "expected": {"a": i} if i % 2 else [i]} for i in range(31)])
    overlap = _rows(40, split="tune")
    overlap += [{"input": _q(i).upper() + "?", "expected_output": "x",
                 "metadata": {"split": "holdout"}} for i in range(25)]
    overlap += [{"input": _q(i), "expected_output": "y"} for i in range(3)]
    add("single_file_overlap_over_cap", overlap)
    named = [{"input": _q(i), "expected_output": "x"} for i in range(12)]
    named += [{"input": _q(i), "expected_output": "x", "split": "train"} for i in range(4)]
    named += _rows(3, start=500, split="holdout")
    add("named_holdout_file_partly_tagged", named, file="eval/holdout.jsonl")
    add("named_holdout_file_untagged_dupes",
        [{"input": _q(i % 4), "expected_output": "x"} for i in range(12)],
        file="eval/heldout.jsonl")
    add("missing_gold_over_cap", [{"input": _q(i)} for i in range(30)])
    add("non_string_inputs",
        [{"input": value, "expected_output": "x"}
         for value in ({"b": 2, "a": 1}, [3, 1], 42, 4.5, None, True, "Plain  Text!")])
    splits = ["Validation", "val", "EVAL", "test", "dev", "holdout", "train"]
    sv = []
    for i in range(35):
        row = {"input": _q(i), "expected_output": "x"}
        if i % 5 == 0:
            row["metadata"] = {"split": 7}
            row["split"] = splits[i % len(splits)]
        elif i % 5 == 1:
            row["metadata"] = "not a dict"
            row["split"] = splits[i % len(splits)]
        elif i % 5 == 2:
            row["metadata"] = {"split": splits[i % len(splits)]}
        elif i % 5 == 3:
            row["split"] = None
        sv.append(row)
    add("split_value_variety", sv)
    add("root_level_file", _rows(31), file="data.jsonl")
    return cases


def _observe_dataset(file: str, raw: audit.RawDataset) -> dict:
    before = _text(asdict(raw))
    report = audit.analyse_dataset(ROOT / file, ROOT, raw)
    return {"report": _report(report), "raw_unchanged": _text(asdict(raw)) == before}


# --------------------------------------------------------------------------
# sibling holdout files
# --------------------------------------------------------------------------


def _sibling_cases() -> dict[str, list[tuple[str, list[dict]]]]:
    overlap_rows = [{"input": _q(i), "expected_output": "x"} for i in range(3)]
    return {
        "untagged_pair_with_overlap": [
            ("eval/tuning.jsonl", _rows(40)),
            ("eval/holdout.jsonl", _rows(32, start=100) + overlap_rows),
        ],
        "untagged_pair_holdout_under_smoke": [
            ("eval/tuning.jsonl", _rows(40)),
            ("eval/holdout.jsonl", _rows(8, start=100)),
        ],
        "untagged_pair_holdout_under_tuning_minimum": [
            ("eval/tuning.jsonl", _rows(40)),
            ("eval/holdout.jsonl", _rows(20, start=100)),
        ],
        "tagged_holdout_file": [
            ("eval/tuning.jsonl", _rows(40)),
            ("eval/holdout.jsonl", _rows(31, start=100, split="holdout")),
        ],
        "mixed_holdout_file": [
            ("eval/tuning.jsonl", _rows(40) + _rows(2, start=300)),
            ("eval/holdout.jsonl",
             _rows(20, start=100, split="holdout")
             + _rows(5, start=0, split="train")
             + _rows(6, start=300)),
        ],
        "train_only_holdout_file": [
            ("eval/tuning.jsonl", _rows(40)),
            ("eval/holdout.jsonl", _rows(30, start=0, split="train")),
        ],
        "tuning_already_tagged": [
            ("eval/tuning.jsonl", _rows(40, split="tune") + _rows(30, start=40, split="test")),
            ("eval/validation.jsonl", _rows(31, start=0)),
        ],
        "partly_tagged_small_holdout": [
            ("eval/tuning.jsonl", _rows(40)),
            ("eval/holdout.jsonl", _rows(5, start=100, split="holdout") + _rows(3, start=200)),
        ],
        "contradicting_tags_with_untagged": [
            ("eval/tuning.jsonl", _rows(40, split="train")),
            ("eval/holdout.jsonl", _rows(3, start=0, split="train") + _rows(32, start=100)),
        ],
        "many_dirs": [
            ("a/train.jsonl", _rows(40)),
            ("a/val.jsonl", _rows(31, start=0)),
            ("a/held-out.jsonl", _rows(12, start=200)),
            ("b/holdout.jsonl", _rows(31)),
            ("c/tuning.jsonl", _rows(31)),
            ("data.jsonl", _rows(40)),
            ("data_holdout.jsonl", _rows(31, start=500)),
        ],
        "holdout_only_dir": [
            ("x/holdout.jsonl", _rows(31)),
            ("x/validation.jsonl", _rows(31)),
        ],
        "tuning_without_rows_beside_holdout": [
            ("eval/tuning.jsonl", []),
            ("eval/holdout.jsonl", []),
        ],
    }


def _observe_siblings(files: list[tuple[str, list[dict]]]) -> list[dict]:
    reports = [
        audit.analyse_dataset(ROOT / name, ROOT, audit.RawDataset(rows=copy.deepcopy(rows)))
        for name, rows in files
    ]
    reports.sort(key=lambda report: report.file)
    audit.apply_sibling_holdouts(reports)
    return [_report(report) for report in reports]


# --------------------------------------------------------------------------
# the next-step ladder
# --------------------------------------------------------------------------


def _knob(name, status):
    return audit.Knob(name=name, values=[], values_readable=True, status=status,
                      file="agent.py", line=5)


def _entry(knobs, note=None):
    return audit.EntryPoint(function="answer", file="agent.py", line=9,
                            knobs=list(knobs), config_space_note=note)


def _scorer(kind="deterministic", function="score"):
    return audit.ScorerCandidate(function=function, file="scorer.py", line=1, kind=kind,
                                 signals=[], parameters=["output", "expected"])


def _inventory(entries=(), scorers=(), files_scanned=7, unparsed=(), total=0):
    inventory = audit.PythonInventory(files_scanned=files_scanned, files_total=total)
    inventory.entry_points = list(entries)
    inventory.scorers = list(scorers)
    inventory.files_unparsed = list(unparsed)
    return inventory


def _ds(file="data.jsonl", rows=80, holdout_rows=40, **extra):
    report = audit.DatasetReport(
        file=file, rows=rows, input_key_counts={"input": rows},
        expected_key_counts={"expected_output": rows}, missing_expected=[],
        exact_duplicate_groups=[], near_duplicate_pairs=[],
        split_counts={"holdout": holdout_rows} if holdout_rows else {},
        holdout_rows=holdout_rows, holdout_overlap=[], label_counts={}, findings=[],
    )
    for key, value in extra.items():
        setattr(report, key, value)
    return report


GOOD = {"ran": True, "scores": {"good": [1.0, 1.0], "partial": [0.5], "bad": [0.0]},
        "errors": []}
UNSTABLE = {"ran": True, "scores": {"good": [0.1, 0.9], "partial": [0.5], "bad": [0.0]},
            "errors": []}
MISORDERED = {"ran": True, "scores": {"good": [0.2, 0.2], "partial": [0.5], "bad": [0.9]},
              "errors": []}


def _next_step_cases() -> dict[str, dict]:
    read = _entry([_knob("model", "read")])
    ok_inv = _inventory([read], [_scorer()])
    skip = ["eval/broken.jsonl could not be parsed (ValueError)",
            "eval/other.jsonl could not be parsed (OSError)"]
    base = {"inventory": ok_inv, "reports": [_ds()], "probe": GOOD, "probed": _scorer()}

    def case(**kw):
        merged = dict(base)
        merged.update(kw)
        return merged

    return {
        "a_no_entry_point": case(inventory=_inventory([], [_scorer()], files_scanned=3)),
        "b_blank_entry": case(inventory=_inventory([_entry([])], [])),
        "b_all_unread": case(inventory=_inventory(
            [_entry([_knob("model", audit.KNOB_UNREAD), _knob("t", audit.KNOB_UNREAD)])], [])),
        "c_no_scorer": case(inventory=_inventory([read], [], files_scanned=4)),
        "d_unstable": case(probe=UNSTABLE, reports=[_ds(rows=5, holdout_rows=0)]),
        "d_misordered": case(probe=MISORDERED),
        "d_with_errors": case(probe={"ran": True, "scores": {"good": [1.0], "partial": [0.5],
                                                             "bad": []},
                                     "errors": [{"case": "bad", "error_type": "KeyError"}]}),
        "e_no_probe": case(probe=None, probed=None, inventory=_inventory(
            [read], [_scorer(), _scorer("llm-judge"), _scorer(), _scorer("code-executing")])),
        "e_failed_probe": case(probe={"ran": False, "stage": "timeout"}),
        "e_blocked_probe": case(probe={"ran": True, "network_blocked": True}),
        "f_unread_no_reports": case(reports=[], skipped_files=skip),
        "f_unread_named_with_reports": case(skipped_files=skip, dataset_named=True),
        "f_unread_discovery_with_reports": case(skipped_files=skip[:1]),
        "f_unread_discovery_with_finding_and_skip": case(
            skipped_files=skip[:1], reports=[_ds(findings=["one finding"])]),
        "f_notes_no_reports": case(reports=[], dataset_notes=[
            "looked at the first 3 of 9 JSONL/JSON/CSV file(s); the rest were not analysed"]),
        "f_notes_and_unread_no_reports": case(
            reports=[], dataset_notes=["note one"], skipped_files=skip),
        "f_no_reports": case(reports=[]),
        "f_unloadable": case(reports=[
            _ds("a.jsonl", rows_without_sdk_input=0),
            _ds("b.jsonl", rows_without_sdk_input=3),
            _ds("c.jsonl", rows_without_sdk_input=9)]),
        "f_gold": case(reports=[
            _ds("a.jsonl", missing_gold_counts={"null": 2}),
            _ds("b.jsonl", missing_gold_counts={"absent": 1, "empty": 4, "nan": 1,
                                                "infinite": 2})]),
        "f_gold_tie": case(reports=[
            _ds("a.jsonl", missing_gold_counts={"null": 2}),
            _ds("b.jsonl", missing_gold_counts={"absent": 2})]),
        "f_overlap_total": case(reports=[
            _ds("a.jsonl", holdout_overlap=[1, 2], holdout_overlap_total=40),
            _ds("b.jsonl", holdout_overlap=[1, 2, 3], holdout_overlap_total=0)]),
        "f_overlap_list_only": case(reports=[
            _ds("a.jsonl", holdout_overlap=[1, 2]),
            _ds("b.jsonl", holdout_overlap=[1, 2, 3])]),
        "f_short_both": case(reports=[_ds(rows=12, holdout_rows=4)]),
        "f_short_rows_only": case(reports=[_ds(rows=12, holdout_rows=40)]),
        "f_short_holdout_only": case(reports=[_ds(rows=80, holdout_rows=12)]),
        "f_short_by_name": case(reports=[
            _ds("holdout.jsonl", rows=12, holdout_rows=12, holdout_by_name=True),
            _ds("tuning.jsonl", rows=80, holdout_rows=40)]),
        "f_short_by_name_tiny_rows_ok": case(reports=[
            _ds("holdout.jsonl", rows=12, holdout_rows=40, holdout_by_name=True)]),
        "f_short_mixed_prefers_tuning": case(reports=[
            _ds("holdout.jsonl", rows=3, holdout_rows=3, holdout_by_name=True),
            _ds("t1.jsonl", rows=20, holdout_rows=40),
            _ds("t2.jsonl", rows=20, holdout_rows=40)]),
        "h_partly_unread": case(inventory=_inventory(
            [_entry([_knob("model", "read"), _knob("t", audit.KNOB_UNREAD)])], [_scorer()])),
        "h_not_inventoried": case(inventory=_inventory(
            [_entry([_knob("model", "read")], note="space built at runtime")], [_scorer()])),
        "h_possibly_read": case(inventory=_inventory(
            [_entry([_knob("model", audit.KNOB_MAYBE)])], [_scorer()])),
        "h_outranked_by_short": case(
            inventory=_inventory(
                [_entry([_knob("model", "read"), _knob("t", audit.KNOB_UNREAD)])],
                [_scorer()]),
            reports=[_ds(rows=5, holdout_rows=0)]),
        "i_one_unparsed": case(inventory=_inventory([read], [_scorer()], unparsed=["x.py"])),
        "i_two_unparsed": case(inventory=_inventory([read], [_scorer()],
                                                    unparsed=["x.py", "y.py"])),
        "i_over_file_cap": case(inventory=_inventory([read], [_scorer()],
                                                     total=audit.MAX_PYTHON_FILES + 1)),
        "f_facts_findings": case(reports=[_ds(findings=["first fact", "second fact"])]),
        "f_facts_notes": case(dataset_notes=["a scan note"]),
        "e_synthetic_probe": case(probe=dict(GOOD, payload_source="synthetic")),
        "g_all_clear": case(),
        "g_dataset_source_probe": case(probe=dict(GOOD, payload_source="dataset")),
    }


def _observe_next_step(case: dict) -> dict:
    case = copy.deepcopy(case)
    kwargs = {key: case[key] for key in ("skipped_files", "dataset_notes", "dataset_named")
              if key in case}
    try:
        step = audit.next_step(case["inventory"], case["reports"], case["probe"],
                               case["probed"], **kwargs)
    except Exception as exc:  # noqa: BLE001 - the raised type is part of the pin
        return {"raised": type(exc).__name__, "message": str(exc)}
    text = _text(step).replace(f"Python {PYVER}", "Python <pyver>")
    return {"step": json.loads(text)}


# --------------------------------------------------------------------------
# reading a stored Tier 1 report
# --------------------------------------------------------------------------


def _base_report() -> dict:
    return {
        "schema": tier2.TIER1_SCHEMA,
        "root": "/proj/healthy",
        "entry_points": [{
            "config_space_note": None, "file": "agent.py", "function": "answer_question",
            "line": 17,
            "knobs": [
                {"file": "agent.py", "line": 12, "name": "model", "status": "read",
                 "values": ["gpt-4o-mini", "claude-haiku-4-5-20251001"],
                 "values_readable": True},
                {"file": "agent.py", "line": 13, "name": "temperature", "status": "read",
                 "values": [0.0, 0.7], "values_readable": True},
            ],
        }],
        "scorer_probe": {
            "dropped_keys": 0, "errors": [], "framed_result_lines": 1,
            "network_guard": "active", "partial_probed": True, "payload_source": "dataset",
            "ran": True, "requested_repeats": 5,
            "scores": {"bad": [0.0], "good": [1.0, 1.0, 1.0, 1.0, 1.0], "partial": [0.5]},
            "stderr_bytes": 0,
        },
        "files": {"dataset_candidates": 1, "dataset_files_not_analysed": [],
                  "python_parsed": 2, "python_total": 2},
        "setup": {"keys": {"names_set_in_environment": ["OPENAI_API_KEY"]},
                  "model_ids_declared": ["claude-haiku-4-5-20251001", "gpt-4o-mini"]},
        "next_step": {"branch": "g", "line": "All clear.", "skills": []},
        "areas": {"agent": {"status": "ok"}, "dataset": {"status": "ok"},
                  "scorer": {"status": "ok"}},
        "datasets": [{"file": "dataset.jsonl", "findings": [], "holdout_rows": 30,
                      "rows": 70}],
        "scorers": [{"file": "scorer.py", "function": "score", "kind": "deterministic",
                     "line": 4}],
    }


def _probe(**changes):
    def mutate(report):
        report["scorer_probe"].update(changes)
    return mutate


def _set(path: tuple, value):
    def mutate(report):
        target = report
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _delete(*keys):
    def mutate(report):
        for key in keys:
            report.pop(key, None)
    return mutate


def _tier1_cases() -> dict[str, object]:
    """name -> mutation of the base report, or raw text for the file, or None
    for a file that is never written."""
    unstable = {"bad": [0.0], "good": [1.0, 0.0, 1.0, 1.0, 1.0], "partial": [0.5]}
    return {
        "base": lambda report: None,
        "missing_file": None,
        "not_json": "{",
        "duplicate_member": '{"schema": "a", "schema": "b"}',
        "nan_schema": '{"schema": NaN}',
        "top_level_list": "[]",
        "wrong_schema": _set(("schema",), "traigent-setup-audit/v0"),
        "schema_only": "SCHEMA_ONLY",
        "no_probe": _delete("scorer_probe"),
        "empty_probe": _set(("scorer_probe",), {}),
        "probe_not_a_dict": _set(("scorer_probe",), "yes"),
        "probe_repeats_none": _probe(requested_repeats=None),
        "probe_repeats_mismatch": _probe(requested_repeats=3),
        "probe_malformed_scores": _probe(scores="x"),
        "probe_not_ran": lambda r: r.__setitem__("scorer_probe", {"ran": False,
                                                                  "stage": "timeout"}),
        "probe_ran_not_bool": _probe(ran="yes"),
        "probe_blocked": lambda r: r.__setitem__("scorer_probe", {
            "ran": False, "network_blocked": True}),
        "probe_unstable": _probe(scores=unstable),
        "probe_unstable_older_report": lambda r: r.__setitem__("scorer_probe", {
            "ran": True, "errors": [], "scores": unstable}),
        "probe_partial_false": _probe(partial_probed=False, scores={
            "bad": [0.0], "good": [1.0] * 5, "partial": []}),
        "probe_partial_false_but_sent": _probe(partial_probed=False),
        "probe_dropped_keys": _probe(dropped_keys=2),
        "probe_misordered": _probe(scores={"bad": [1.0], "good": [0.0] * 5, "partial": [0.5]}),
        "entry_points_mixed": _set(("entry_points",), [
            "junk", 3, {"function": "f", "file": "a.py", "line": 1, "knobs": [],
                        "config_space_note": None}]),
        "entry_points_string": _set(("entry_points",), "abc"),
        "entry_points_none": _set(("entry_points",), None),
        "knob_not_a_dict": _set(("entry_points", 0, "knobs"), ["x"]),
        "knob_bad_status": _set(("entry_points", 0, "knobs", 0, "status"), "weird"),
        "knob_missing_status": lambda r: r["entry_points"][0]["knobs"][0].pop("status"),
        "knob_unread": _set(("entry_points", 0, "knobs", 1, "status"),
                            audit.KNOB_UNREAD),
        "entry_without_knobs_key": lambda r: r["entry_points"][0].pop("knobs"),
        "areas_missing": _delete("areas"),
        "areas_list": _set(("areas",), ["agent"]),
        "areas_agent_not_dict": _set(("areas", "agent"), "ok"),
        "areas_status_none": _set(("areas", "dataset", "status"), None),
        "areas_status_zero": _set(("areas", "agent", "status"), 0),
        "datasets_findings_mixed": _set(("datasets",), [
            "junk", {"file": "a.jsonl", "findings": [3, "first finding", "second"],
                     "rows": 4},
            {"file": "b.jsonl", "findings": ["b finding"], "rows": 99,
             "holdout_rows": 0}]),
        "datasets_not_analysed_only": lambda r: (
            r["datasets"][0].__setitem__("findings", None),
            r["files"].__setitem__("dataset_files_not_analysed",
                                   [5, "x.csv could not be parsed (Error)"])),
        "files_python_gap": _set(("files",), {"python_total": 5, "python_parsed": 3,
                                              "dataset_candidates": 7}),
        "files_bad_int": _set(("files", "python_total"), "abc"),
        "files_missing": _delete("files"),
        "setup_typed": _set(("setup",), {"keys": {"names_set_in_environment": ["A", 2]},
                                         "model_ids_declared": [1, "m"]}),
        "setup_keys_none": _set(("setup",), {"keys": None}),
        "next_step_missing": _delete("next_step"),
        "next_step_branch_none": _set(("next_step",), {"branch": None, "line": None}),
        "root_none": _set(("root",), None),
        "scorers_mixed": _set(("scorers",), ["junk", {"function": "s"}]),
        "stale_all_clear": _set(("areas", "dataset", "status"), "attention"),
    }


def _observe_tier1(name: str, spec) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.json"
        if spec is not None:
            if callable(spec):
                report = _base_report()
                spec(report)
                text = json.dumps(report)
            elif spec == "SCHEMA_ONLY":
                text = json.dumps({"schema": tier2.TIER1_SCHEMA})
            else:
                text = spec
            path.write_text(text, encoding="utf-8")
        try:
            tier1 = tier2.load_tier1(path)
        except Exception as exc:  # noqa: BLE001 - the raised type is part of the pin
            return {"raised": type(exc).__name__,
                    "message": str(exc).replace(tmp, "<tmp>")}
        observed = asdict(tier1)
        observed["path"] = str(tier1.path).replace(tmp, "<tmp>")
        observed["stale_subjects"] = tier1.stale_subjects
        observed["stale_all_clear"] = tier1.stale_all_clear
        observed["has_holdout"] = tier1.has_holdout
        observed["dataset_size"] = tier1.dataset_size
        return json.loads(_text(observed))


# --------------------------------------------------------------------------
# Tier 2 motivations
# --------------------------------------------------------------------------


def _tier1(**changes) -> tier2.Tier1:
    values = dict(
        path=Path("/proj/report.json"),
        root="/proj",
        branch="g",
        next_step_line="Entry point, knobs, dataset and scorer all check out.",
        entry_points=[{"function": "f", "file": "a.py", "line": 3, "knobs": [],
                       "config_space_note": None}],
        knob_count=3,
        read_knob_count=2,
        knob_wiring={"verdict": "read", "summary": "", "knob_count": 3, "read_count": 3,
                     "entry": None, "knobs": []},
        agent_status="ok",
        dataset_status="ok",
        dataset_detail="",
        python_gap="",
        datasets=[
            {"file": "a.jsonl", "rows": 70, "holdout_rows": 30, "findings": []},
            {"file": "b.jsonl", "rows": 12, "holdout_rows": 0,
             "findings": ["12 rows is under the 30-row first-tuning-slice minimum",
                          "second finding"]},
        ],
        scorers=[{"function": "score"}],
        probe_verdict="repeatable",
        probe_symptom="",
        probe_remedy="",
        probe_consequence="",
        model_ids=["gpt-4o-mini", "claude-haiku"],
        dataset_candidates=4,
        python_files=6,
        key_names_set=[],
    )
    values.update(changes)
    return tier2.Tier1(**values)


def _motivation_tier1s() -> dict[str, tier2.Tier1]:
    partly = {"verdict": "partly-unread", "entry": None, "knobs": [],
              "summary": "`f` at a.py:3 declares 2 knob(s) and the body never reads 1 "
                         "of them (`t`)"}
    return {
        "full": _tier1(),
        "empty": _tier1(datasets=[], scorers=[], model_ids=[], next_step_line="",
                        knob_wiring={"verdict": "none"}, knob_count=0,
                        read_knob_count=0, entry_points=[], branch=""),
        "wiring_partly_unread": _tier1(knob_wiring=partly, branch="h"),
        "wiring_unreadable": _tier1(knob_wiring={
            "verdict": "unreadable", "summary": "its stored entry points could not be read"}),
        "wiring_no_summary": _tier1(knob_wiring={"verdict": "possibly-read"}),
        "wiring_not_inventoried": _tier1(knob_wiring={
            "verdict": "not-inventoried", "summary": "s",
            "entry": {"function": "f", "file": "a.py", "line": 3}}),
        "wiring_blank": _tier1(knob_wiring={"verdict": "blank",
                                            "summary": "`f` at a.py:3 declares 0 knobs"}),
        "zero_knobs_read_verdict": _tier1(knob_count=0, read_knob_count=0),
        "no_dataset": _tier1(datasets=[]),
        "no_scorer": _tier1(scorers=[], probe_verdict="none"),
        "no_dataset_no_scorer": _tier1(datasets=[], scorers=[], probe_verdict="none"),
        "probe_unreliable_measured": _tier1(
            probe_verdict="unreliable", probe_symptom="gave 2 different scores",
            probe_remedy="make it repeatable", probe_consequence=tier2.SCORER_MEASURED,
            branch="d"),
        "probe_unreliable_other": _tier1(
            probe_verdict="unreliable", probe_symptom="raised on 1 call",
            probe_remedy="fix the failing call",
            probe_consequence="its reliability is not established", branch="d"),
        "probe_not_run_with_scorers": _tier1(probe_verdict="not-run",
                                             probe_symptom="the probe timed out",
                                             branch="e"),
        "probe_none_no_scorers": _tier1(probe_verdict="none", scorers=[], python_files=0),
        "smallest_findings_none": _tier1(datasets=[
            {"file": "only.jsonl", "rows": 40, "holdout_rows": None, "findings": None}]),
        "stale_one_subject": _tier1(agent_status="attention"),
        "stale_three_subjects": _tier1(agent_status="", dataset_status="",
                                       probe_verdict="not-run", probe_symptom=""),
        "stale_with_details": _tier1(dataset_status="attention",
                                     dataset_detail="a.jsonl: finding",
                                     probe_verdict="unreliable",
                                     probe_symptom="gave 2 scores",
                                     knob_wiring={"verdict": "partly-unread",
                                                  "summary": "partly"}),
        "stale_root_empty": _tier1(root="", agent_status="attention", python_gap="1 gap"),
        "stale_root_spaces": _tier1(root="/my proj/x", path=Path("/my proj/r e.json"),
                                    dataset_status="attention"),
        "not_stale_branch_f": _tier1(branch="f", next_step_line="Grow the dataset."),
    }


def _motivation_ids() -> list[str]:
    return [check.id for check in tier2.CATALOGUE] + ["unknown-check"]


def _observe_motivation(tier1: tier2.Tier1, check_id: str) -> dict:
    try:
        text = tier2.motivation(check_id, tier1, None)
        with_run = tier2.motivation(check_id, tier1, "run_12345678")
    except Exception as exc:  # noqa: BLE001 - the raised type is part of the pin
        return {"raised": type(exc).__name__, "message": str(exc)}
    return {"text": text, "run_id_changes_text": with_run != text}


# --------------------------------------------------------------------------
# Tier 2 run mode
# --------------------------------------------------------------------------

UA = "traigent-sdk/0.0-pin"
KEY = "pin-not-a-real-key"


class _FixedDatetime:
    @staticmethod
    def now(tz=None):
        return datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz or timezone.utc)


def _execute_cases() -> dict[str, dict]:
    every = ["stop-here", "plan", "list-runs", "decision-brief", "example-scoring",
             "example-insights", "evaluator-quality", "model-ids", "plan", "nope"]
    executable = [c for c in every if c not in {"stop-here", "nope"}]
    return {
        "blocked_needs_run": {"approve": ["decision-brief"]},
        "blocked_plan_needs_cap": {"approve": ["plan"], "run_id": "run_12345678"},
        "blocked_bounded_run": {"approve": ["bounded-run"]},
        "blocked_after_an_unblocked_one": {"approve": ["stop-here", "model-ids"]},
        "no_key": {"approve": ["list-runs"], "key": None},
        "empty_key": {"approve": ["list-runs"], "key": ""},
        "model_ids_without_key_or_sdk": {"approve": ["model-ids"], "key": None, "ua": None},
        "no_user_agent": {"approve": ["list-runs"], "ua": None},
        "no_cli_on_path": {"approve": ["plan", "list-runs", "model-ids"], "cost": 5.0,
                           "which": None},
        "no_cli_needed_and_none_on_path": {"approve": ["list-runs"], "which": None},
        "every_check_with_receipt_and_json": {
            "approve": executable + ["nope"], "run_id": "run_12345678", "cost": 5.0,
            "receipt": "nested/dir/receipt.json", "json": "out/run.json"},
        "list_runs_no_receipt_no_json": {"approve": ["list-runs", "nope"]},
        "receipt_only": {"approve": ["evaluator-quality"], "run_id": "run_12345678",
                         "receipt": "receipt.json"},
        "json_only": {"approve": ["example-insights"], "run_id": "run_12345678",
                      "json": "only.json"},
        "a_check_raises": {"approve": ["list-runs", "model-ids"], "raise": "list-runs"},
        "nothing_approved_from_catalogue": {"approve": ["nope"]},
    }


def _observe_execute(case: dict) -> dict:
    calls: list = []
    raise_on = case.get("raise")

    class FakeTransport:
        def __init__(self, **kwargs):
            calls.append(["Transport", sorted((k, str(v)) for k, v in kwargs.items())])
            self.requests: list[dict] = []

        def close(self):
            calls.append(["close"])

    def backend_check(check_id):
        def run(transport, *rest):
            out = rest[-1]
            calls.append([check_id, [str(item) for item in rest[:-1]]])
            if raise_on == check_id:
                raise RuntimeError(f"{check_id} failed")
            transport.requests.append({"check": check_id, "status": 200})
            out.append(f"{check_id} line\x1b[2K with\tcontrol")
            return {"check": check_id, "path": Path("/p") / check_id}
        return run

    def cli_check(check_id):
        def run(*rest):
            out = rest[-1]
            subprocesses = rest[-3]
            api_key = rest[-2]
            calls.append([check_id, type(rest[0]).__name__,
                          [str(item) for item in rest[1:-3]], bool(api_key)])
            if raise_on == check_id:
                raise RuntimeError(f"{check_id} failed")
            subprocesses.append({"check": check_id})
            out.append(f"{check_id} ran")
            return {"check": check_id}
        return run

    args = argparse.Namespace(
        approve=list(case.get("approve", [])),
        run_id=case.get("run_id"),
        cost_limit=case.get("cost"),
        timeout=12.5,
        receipt=None,
        json_out=None,
    )
    tier1 = _tier1()
    stdout, stderr = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        if case.get("receipt"):
            args.receipt = str(Path(tmp) / case["receipt"])
        if case.get("json"):
            args.json_out = str(Path(tmp) / case["json"])
        key = case.get("key", KEY)
        env = {} if key is None else {tier2.KEY_ENV_NAME: key}
        which = case.get("which", "/fake/bin/traigent")
        patches = [
            mock.patch.object(tier2, "Transport", FakeTransport),
            mock.patch.object(tier2, "sdk_user_agent", lambda: case.get("ua", UA)),
            mock.patch.object(tier2.shutil, "which", lambda name: which),
            mock.patch.object(tier2, "datetime", _FixedDatetime),
            mock.patch.object(tier2, "run_evaluator_quality",
                              backend_check("evaluator-quality")),
            mock.patch.object(tier2, "run_example_insights",
                              backend_check("example-insights")),
            mock.patch.object(tier2, "run_decision_brief",
                              backend_check("decision-brief")),
            mock.patch.object(tier2, "run_example_scoring",
                              backend_check("example-scoring")),
            mock.patch.object(tier2, "run_list_runs", backend_check("list-runs")),
            mock.patch.object(tier2, "run_model_ids", cli_check("model-ids")),
            mock.patch.object(tier2, "run_plan", cli_check("plan")),
        ]
        saved = os.environ.pop(tier2.KEY_ENV_NAME, None)
        try:
            with contextlib.ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                stack.enter_context(mock.patch.dict(os.environ, env))
                stack.enter_context(contextlib.redirect_stdout(stdout))
                stack.enter_context(contextlib.redirect_stderr(stderr))
                try:
                    result: dict = {"returned": tier2.execute(
                        args, tier1, "https://backend.example", {"x": "y"})}
                except Exception as exc:  # noqa: BLE001 - the raised type is pinned
                    result = {"raised": type(exc).__name__, "message": str(exc)}
        finally:
            if saved is not None:
                os.environ[tier2.KEY_ENV_NAME] = saved
        written = {}
        for name in ("receipt", "json_out"):
            target = getattr(args, name)
            if target:
                file = Path(target)
                written[name] = (file.read_text(encoding="utf-8").replace(tmp, "<tmp>")
                                 if file.exists() else None)
        result.update({
            "stdout": stdout.getvalue().replace(tmp, "<tmp>"),
            "stderr": stderr.getvalue().replace(tmp, "<tmp>"),
            "calls": json.loads(_text(calls).replace(tmp, "<tmp>")),
            "written": written,
        })
    return result


# --------------------------------------------------------------------------
# collection, the record, and the tests
# --------------------------------------------------------------------------


def collect() -> dict[str, dict]:
    observed: dict[str, dict] = {}
    for name, (file, raw) in _dataset_cases().items():
        observed[f"analyse_dataset/{name}"] = _observe_dataset(file, raw)
    for name, files in _sibling_cases().items():
        observed[f"apply_sibling_holdouts/{name}"] = _observe_siblings(files)
    for name, case in _next_step_cases().items():
        observed[f"next_step/{name}"] = _observe_next_step(case)
    for name, spec in _tier1_cases().items():
        observed[f"load_tier1/{name}"] = _observe_tier1(name, spec)
    for name, tier1 in _motivation_tier1s().items():
        for check_id in _motivation_ids():
            observed[f"motivation/{name}/{check_id}"] = _observe_motivation(tier1, check_id)
    for name, case in _execute_cases().items():
        observed[f"execute/{name}"] = _observe_execute(case)
    return {key: json.loads(_text(value)) for key, value in observed.items()}


def _recorded() -> dict:
    return json.loads(PINS.read_text(encoding="utf-8"))


_OBSERVED: dict | None = None


def _observed() -> dict:
    global _OBSERVED
    if _OBSERVED is None:
        _OBSERVED = collect()
    return _OBSERVED


def _case_ids() -> list[str]:
    # A missing record is a failure of the completeness test below, not an
    # import error that would also stop `--write` from creating it.
    return sorted(_recorded()) if PINS.exists() else []


def test_every_case_has_a_record_and_every_record_a_case() -> None:
    assert sorted(_observed()) == _case_ids()


@pytest.mark.parametrize("case_id", _case_ids())
def test_behaviour_matches_the_record(case_id: str) -> None:
    observed = _observed()
    assert case_id in observed, f"{case_id} is recorded but no longer produced"
    assert _text(observed[case_id]) == _text(_recorded()[case_id])


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true",
                       help="rewrite the record from the code as it stands")
    group.add_argument("--dump", metavar="PATH", help="write observations to PATH")
    options = parser.parse_args(argv)
    observed = collect()
    # One case per line, so a behaviour change shows as a one-line diff.
    text = (
        "{\n"
        + ",\n".join(
            f"{json.dumps(key)}: {_text(value)}" for key, value in observed.items()
        )
        + "\n}\n"
    )
    target = PINS if options.write else Path(options.dump)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"{len(observed)} case(s) written to {target}")
    print(f"audit_project: {audit.__file__}")
    print(f"tier2_checks: {tier2.__file__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
