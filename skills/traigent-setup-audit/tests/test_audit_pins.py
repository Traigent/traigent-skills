"""Pin what the Tier 1 audit's readers, probe checks, area cards and report
builder return.

Covers the static Python inventory (traigent aliases, entry points, knob
values, read surfaces, scorer classification, the file scan), the dataset file
readers, near-duplicate pairing, the probe payload and its validators, the
probe reading and summary, the venv and key lookups, the knob wiring reading,
the four area cards, the network guard and ``build_report`` itself.

Each case is run and its observation compared, ordering included, with the
recorded observation in ``pins/audit_pins.json``. The record was written from
the code before these functions were restructured, so any difference is a
behaviour change rather than a style change. Regenerate it only for an
intended change, and review the diff of the JSON file:

    python tests/test_audit_pins.py --write

``--dump PATH`` writes the observations without comparing, so two copies of
the scripts can be run over the same cases and their outputs diffed.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import math
import os
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from unittest import mock

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
PINS = TESTS_DIR / "pins" / "audit_pins.json"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_project as audit  # noqa: E402

TMP_MARK = "<tmp>"


# --------------------------------------------------------------------------
# serialising observations
# --------------------------------------------------------------------------


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=repr)
    if isinstance(value, float) and not math.isfinite(value):
        return f"<float {value!r}>"
    if isinstance(value, Path):
        return f"<path {value.as_posix()}>"
    if isinstance(value, ast.AST):
        return f"<ast {ast.dump(value)}>"
    return value


def _text(value: object) -> str:
    """Canonical, order-preserving text of one observation."""
    return json.dumps(_jsonable(value), ensure_ascii=False, allow_nan=False)


def _call(function: Callable[..., object], *args: object, **kwargs: object) -> dict:
    """The return value, or the raised type and message."""
    try:
        return {"returned": _jsonable(function(*args, **kwargs))}
    except Exception as exc:  # noqa: BLE001 - the raised type is pinned
        return {"raised": type(exc).__name__, "message": str(exc)}


def _scrub(value: object, tmp: str) -> object:
    """Replace a temporary directory in every string of an observation."""
    real = os.path.realpath(tmp)
    text = _text(value).replace(real, TMP_MARK).replace(tmp, TMP_MARK)
    return json.loads(text)


@contextmanager
def _tmpdir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _write(root: Path, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")


def _jsonl(rows: list[object]) -> str:
    return "".join(json.dumps(row) + "\n" for row in rows)


# --------------------------------------------------------------------------
# Python sources: aliases, entry points, knobs, read surfaces, scorers
# --------------------------------------------------------------------------


SOURCES: dict[str, str] = {
    "no_traigent": """
        import os
        from os import path
        from . import sibling

        def score(output, expected):
            return float(output == expected)
    """,
    "import_forms": """
        import traigent
        import traigent.api as tapi
        import traigent.config
        from traigent import optimize
        from traigent import optimize as opt
        from traigent.api import Range, Choices as C
        from traigent_extra import optimize as not_ours
        import traigentx

        @traigent.optimize
        def bare_attribute(question):
            return question

        @tapi.optimize(objectives=["accuracy"])
        def no_space(question):
            return question

        @optimize()
        def bare_call(question):
            return question

        @opt(configuration_space={"model": ["a", "b"], "temperature": [0.0, 0.5]})
        async def async_entry(question, model, *, temperature=0.1):
            return f"{model}{temperature}{question}"

        @not_ours(configuration_space={"model": ["x"]})
        def foreign(question):
            return question

        @study.optimize(config_space={"model": ["x"]})
        def optuna_like(question):
            return question

        @a.b.optimize(config_space={"model": ["x"]})
        def nested_attribute(question):
            return question

        @factory()(config_space={"model": ["x"]})
        def called_call(question):
            return question

        @other
        def undecorated(question):
            return question
    """,
    "space_forms": """
        import traigent
        from traigent import optimize, ConfigurationSpace, ConfigSpace, Choices

        SPACE = {"model": ["gpt-a", "gpt-b"], "top_k": [1, 2, 3]}
        TYPED: dict = {"engine": ("e1", "e2")}
        NOT_A_DICT = ["model"]
        A = B = {"llm": ["l1"]}
        x, y = 1, 2

        @traigent.optimize(config_space=SPACE)
        def by_name(question, model, **config):
            return config["top_k"]

        @traigent.optimize(configuration_space=TYPED)
        def by_annotated_name(question):
            return question

        @traigent.optimize(configuration_space=UNKNOWN_NAME)
        def unknown_name(question):
            return question

        @traigent.optimize(configuration_space=ConfigurationSpace({"model": ["m"], 1: ["n"], **SPACE}))
        def wrapped(question, model):
            return model

        @traigent.optimize(configuration_space=traigent.ConfigSpace(SPACE))
        def wrapped_attribute(question):
            return question.get("model")

        @traigent.optimize(configuration_space=ConfigSpace())
        def wrapped_empty(question):
            return question

        @traigent.optimize(configuration_space=dict(model=["d1", "d2"], temperature=Choices(0.1, 0.2), **extra))
        def dict_call(question, cfg=None):
            return cfg.model

        @traigent.optimize(configuration_space=dict())
        def dict_call_empty(question):
            return question

        @traigent.optimize(configuration_space=build_space(
            "a very long argument that makes the expression text exceed the eighty character limit",
        ))
        def computed(question):
            return question

        @traigent.optimize(configuration_space=lambda: {"model": ["x"]})
        def lambda_space(question):
            return question

        @traigent.optimize(configuration_space={}, config_space={"model": ["late"]})
        def two_keywords(question):
            return question

        @traigent.optimize(configuration_space={"model": ["z"]})
        @traigent.optimize(configuration_space={"llm": ["first wins"]})
        def stacked(question):
            return question
    """,
    "knob_values": """
        from traigent import optimize, Choices, Categorical, Range

        @optimize(configuration_space={
            "a_list": ["x", "y"],
            "b_tuple": ("x", 1),
            "c_set": {3},
            "d_nan": [1e999],
            "e_choices": Choices("p", "q"),
            "f_choices_model": Choices.model("m1", "m2"),
            "g_categorical": Categorical(1, 2),
            "h_choices_name": Choices(VALUE),
            "i_choices_empty": Choices(),
            "j_choices_inf": Choices(1e999),
            "k_range": Range(0.0, 1.0),
            "l_deep": mod.sub.Choices("a"),
            "m_name": SOME_LIST,
            "n_scalar": "just text",
            "o_none_in_choices": Choices(None, "b"),
            "p_call_attr_other": Other.model("x"),
        })
        def knobs(question, a_list, **options):
            options.get("b_tuple")
            return f(**options)
    """,
    "read_surfaces": """
        import traigent
        from traigent import get_config

        @traigent.optimize(configuration_space={
            "model": ["a"], "temperature": [0.1], "top_k": [1], "mode": ["m"],
            "unused": ["u"],
        })
        def positional(model, /, temperature, *rest, top_k=1, **kw):
            text = "mode"
            return kw

        @traigent.optimize(configuration_space={"model": ["a"], "style": ["s"]})
        def through_call(question):
            settings = traigent.get_current_config()
            return question

        @traigent.optimize(configuration_space={"model": ["a"], "style": ["s"]})
        def through_name_call(question):
            return get_config()

        @traigent.optimize(configuration_space={"model": ["a"], "style": ["s"]})
        def through_splat(question, **params):
            return run(question, **params)

        @traigent.optimize(configuration_space={"model": ["a"], "style": ["s"]})
        def through_other_splat(question, **ignored):
            return run(question, **other)

        @traigent.optimize(configuration_space={"model": ["a"], "style": ["s"]})
        def through_attribute(question):
            return settings.style

        @traigent.optimize(configuration_space={"model": ["a"], "style": ["s"]})
        def never(question):
            return question.upper()

        @traigent.optimize(configuration_space={"model": ["a"]})
        def no_args():
            return "model"

        class Holder:
            @traigent.optimize(configuration_space={"model": ["a"]})
            def method(self, question):
                return self.model
    """,
    "judge_scorer": """
        import openai
        import anthropic.types

        def score_with_judge(output, expected):
            return openai.chat(output, expected)
    """,
    "executing_scorer": """
        import os
        import subprocess
        import importlib

        def grade(output, expected):
            os.fork()
            os.path.join("a", "b")
            os.getcwd()
            importlib.reload(os)
            factory().reload()
            import_module("json")
            import_module(name)
            import_module()
            getattr(os, "fork")
            getattr(thing, "attr")
            getattr(thing, name)
            getattr()
            (lambda: 1)()
            sys.modules
            other.modules
            a.b.modules
            return 1.0
    """,
    "hybrid_scorer": """
        import openai
        import ctypes

        def metric_answer(output, expected):
            return 0.0
    """,
    "judge_and_exec_call": """
        import cohere

        def evaluate_answer(output, expected):
            return compile("1", "f", "eval")
    """,
    "candidates": """
        import openai

        def score(output, expected):
            return 1.0

        def _score_private(output, expected):
            return 1.0

        def check_stage(body, expected):
            return body == expected

        def compare(output, expected_output):
            return output == expected_output

        def answer(question):
            return openai.chat(question)

        def _helper(question):
            return question

        def lonely():
            return None

        def accuracy_score(prediction):
            return 1.0
    """,
}


def _dedent(source: str) -> str:
    return textwrap.dedent(source).lstrip("\n")


def _functions(tree: ast.AST) -> list[ast.AST]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _observe_source(source: str) -> dict:
    tree = ast.parse(_dedent(source))
    modules, optimize_names = audit._traigent_aliases(tree)
    surfaces = {}
    classified = {}
    for node in _functions(tree):
        parameters, literals, dynamic = audit.function_read_surface(node)
        surfaces[f"{node.name}@{node.lineno}"] = [
            sorted(parameters), sorted(literals), dynamic,
        ]
        classified[f"{node.name}@{node.lineno}"] = audit.classify_scorer(tree, node)
    return {
        "aliases": [sorted(modules), sorted(optimize_names)],
        "entry_points": _call(audit.collect_entry_points, tree, "pkg/mod.py"),
        "read_surfaces": surfaces,
        "classified": _jsonable(classified),
        "module_surface": _jsonable(audit.function_read_surface(tree)),
    }


EXPRESSIONS: dict[str, str] = {
    "dict_literal": '{"a": [1]}',
    "known_name": "SPACE",
    "unknown_name": "MISSING",
    "wrapper_name": "ConfigurationSpace(SPACE)",
    "wrapper_attr": "lib.ConfigSpace({'b': [2]})",
    "wrapper_no_args": "ConfigSpace()",
    "wrapper_nested": "ConfigSpace(ConfigurationSpace({'c': [3]}))",
    "dict_keywords": "dict(a=[1], **more)",
    "dict_only_splat": "dict(**more)",
    "dict_no_keywords": "dict({'a': [1]})",
    "other_call": "make_space()",
    "call_of_call": "factory()({'a': [1]})",
    "subscript": "SPACES['x']",
    "list_literal": "[1, 2]",
    "tuple_literal": "(1, 'a')",
    "set_literal": "{1}",
    "nan_list": "[1e999]",
    "nested_list": "[[1], {'k': (2, 3)}]",
    "choices": "Choices('a', 'b')",
    "choices_attr": "Choices.model('a')",
    "categorical": "Categorical(1)",
    "choices_unknown": "Choices(x)",
    "choices_empty": "Choices()",
    "choices_inf": "Choices(1e999)",
    "choices_bytes": "Choices(b'raw')",
    "choices_deep_attr": "a.Choices('x')",
    "range_call": "Range(0, 1)",
    "string": "'text'",
    "number": "3",
    "lambda": "lambda: [1]",
    "call_on_subscript": "items[0]('a')",
}


def _observe_expression(text: str) -> dict:
    constants = audit.module_dict_constants(ast.parse("SPACE = {'s': [1, 2]}"))
    node = ast.parse(text, mode="eval").body
    space, pairs = audit.resolve_config_space(node, constants)
    return {
        "resolve_config_space": [
            None if space is None else ast.dump(space),
            None if pairs is None else [[key, ast.dump(value)] for key, value in pairs],
        ],
        "knob_values": _call(audit.knob_values, node),
    }


def _scan_cases() -> dict[str, dict[str, str | bytes]]:
    sources = {f"src/{name}.py": _dedent(text) for name, text in SOURCES.items()}
    return {
        "all_sources": {
            **sources,
            "src/broken.py": "def broken(:\n",
            "src/nul.py": b"x = 1\x00\n",
            "tests/test_scoring.py": "def score_case(output, expected):\n    return 1\n",
            "evaluation/judge_eval.py": "def compare(item, expected):\n    return 1\n",
            "lib/plain.py": "def compare(item, expected):\n    return 1\n",
            "bom.py": "﻿def score(output, expected):\n    return 1\n",
        },
        "empty": {},
        "only_unparsed": {"a.py": "def (\n", "b.py": "class\n"},
    }


def _observe_scan(name: str, files: dict[str, str | bytes], limit: int | None) -> dict:
    with _tmpdir() as root:
        _write(root, files)
        paths = sorted(path for path in root.rglob("*.py"))
        paths.append(root / "missing.py")
        with ExitStack() as stack:
            if limit is not None:
                stack.enter_context(mock.patch.object(audit, "MAX_PYTHON_FILES", limit))
            result = _call(audit.scan_python, paths, root)
        return _scrub(result, str(root))


# --------------------------------------------------------------------------
# dataset files
# --------------------------------------------------------------------------


def _rows(n: int, *, start: int = 0, gold: object = "answer", split: str | None = None) -> list:
    rows = []
    for i in range(start, start + n):
        row: dict = {"input": f"question {i} about item {i * 3}", "expected_output": gold}
        if split is not None:
            row["split"] = split
        rows.append(row)
    return rows


def _dataset_files() -> dict[str, str | bytes]:
    return {
        "ok.jsonl": _jsonl(_rows(12)),
        "blank_lines.jsonl": "\n\n" + _jsonl(_rows(3)) + "   \n",
        "some_bad.jsonl": _jsonl(_rows(3)) + "{not json\n" + "[1, 2]\n" + '"text"\n',
        "all_bad.jsonl": "{nope\n{also nope\n",
        "only_non_objects.jsonl": "[1]\n2\n",
        "constants.jsonl": '{"input": "q", "expected_output": NaN}\n'
        '{"input": "r", "expected_output": Infinity}\n'
        '{"input": "s", "expected_output": -Infinity}\n'
        '{"input": "t", "expected_output": NaN}\n',
        "long.jsonl": _jsonl(_rows(9)),
        "bom.jsonl": "﻿" + _jsonl(_rows(2)),
        "bad_utf8.jsonl": b'{"input": "caf\xe9", "expected_output": "x"}\n',
        "empty.jsonl": "",
        "list.json": json.dumps(_rows(4) + [1, "two", None]),
        "long_list.json": json.dumps(_rows(9)),
        "nested.json": json.dumps({"meta": 1, "data": _rows(3)}),
        "nested_second.json": json.dumps({"a": [], "b": [1], "c": [{"x": 1}],
                                          "d": [{"question": "q"}]}),
        "object.json": json.dumps({"model": "x"}),
        "scalar.json": "3",
        "invalid.json": "{oops",
        "constants.json": '[{"input": "q", "expected_output": NaN}]',
        "empty_list.json": "[]",
        "rows.csv": "input,expected_output\nq1,a1\nq2,a2\n",
        "long.csv": "input,label\n" + "".join(f"q{i},l{i}\n" for i in range(9)),
        "header_only.csv": "input,label\n",
        "bad_utf8.csv": b"input,label\nq\xff,a\n",
        "notes.txt": "input: not a dataset\n",
        "dir.jsonl/inner.txt": "a directory with a dataset suffix",
        "holdout.jsonl": "",
        "config.json": json.dumps({"name": "pkg", "version": "1"}),
        "no_input.jsonl": _jsonl([{"text": "x", "label": "y"}] * 3),
        "half_input.jsonl": _jsonl([{"input": "a"}, {"other": 1}, {"other": 2}]),
        "majority_input.jsonl": _jsonl([{"input": "a"}, {"input": "b"}, {"other": 2}]),
        "wrapped.json": json.dumps({"rows": [{"input": "q"}]}),
        "UPPER.JSONL": _jsonl(_rows(2)),
    }


def _observe_load_rows(root: Path, name: str) -> dict:
    return _scrub(_call(audit.load_rows, root / name), str(root))


def _observe_read_dataset(root: Path, name: str, named: bool) -> dict:
    return _scrub(
        _call(audit._read_dataset, root / name, root, named=named), str(root)
    )


def _load_row_observations() -> dict[str, object]:
    observed: dict[str, object] = {}
    with _tmpdir() as root:
        _write(root, _dataset_files())
        names = sorted(_dataset_files()) + ["missing.jsonl", "dir.jsonl"]
        names.remove("dir.jsonl/inner.txt")
        with mock.patch.object(audit, "MAX_ROWS", 5):
            for name in names:
                observed[f"load_rows/{name}"] = _observe_load_rows(root, name)
                for named in (False, True):
                    observed[f"_read_dataset/{name}/named={named}"] = _observe_read_dataset(
                        root, name, named
                    )
        with mock.patch.object(audit, "MAX_DATA_BYTES", 10):
            observed["load_rows/over_byte_cap"] = _observe_load_rows(root, "ok.jsonl")
        with mock.patch.object(audit.csv, "DictReader", side_effect=audit.csv.Error("bad")):
            observed["load_rows/csv_error"] = _observe_load_rows(root, "rows.csv")
        observed["load_rows/full_caps/ok.jsonl"] = _observe_load_rows(root, "ok.jsonl")
    return observed


def _explicit_layouts() -> dict[str, dict]:
    tuning = _jsonl(_rows(40))
    holdout = _jsonl(_rows(31, start=100))
    return {
        "named_with_holdout_siblings": {
            "files": {
                "data/tuning.jsonl": tuning,
                "data/holdout.jsonl": holdout,
                "data/val.csv": "input,expected_output\nq,a\n",
                "data/validation.json": json.dumps(_rows(2, start=300)),
                "data/heldout.txt": "not a dataset suffix",
                "data/notes.jsonl": _jsonl(_rows(2, start=400)),
                "data/held-out.jsonl": "{broken\n",
                "data/holdout_dir.jsonl/x": "a directory",
            },
            "named": "data/tuning.jsonl",
        },
        "named_holdout_itself": {
            "files": {"data/tuning.jsonl": tuning, "data/holdout.jsonl": holdout},
            "named": "data/holdout.jsonl",
        },
        "named_missing_file": {
            "files": {"data/holdout.jsonl": holdout},
            "named": "data/absent.jsonl",
        },
        "named_in_missing_dir": {"files": {}, "named": "nowhere/data.jsonl"},
        "named_empty": {
            "files": {"data/tuning.jsonl": "", "data/holdout.jsonl": ""},
            "named": "data/tuning.jsonl",
        },
        "named_symlink_to_holdout": {
            "files": {"data/holdout.jsonl": holdout},
            "named": "data/tuning.jsonl",
            "symlink": ("data/tuning.jsonl", "holdout.jsonl"),
        },
        "over_sibling_cap": {
            "files": {
                "data/tuning.jsonl": tuning,
                "data/holdout.jsonl": holdout,
                "data/val.jsonl": holdout,
                "data/validation.jsonl": holdout,
            },
            "named": "data/tuning.jsonl",
            "cap": 2,
        },
        "iterdir_fails": {
            "files": {"data/tuning.jsonl": tuning, "data/holdout.jsonl": holdout},
            "named": "data/tuning.jsonl",
            "iterdir_fails": True,
        },
    }


def _observe_explicit(spec: dict) -> dict:
    with _tmpdir() as root:
        _write(root, spec["files"])
        if "symlink" in spec:
            link, target = spec["symlink"]
            (root / link).symlink_to(target)
        with ExitStack() as stack:
            if "cap" in spec:
                stack.enter_context(mock.patch.object(audit, "MAX_DATA_FILES", spec["cap"]))
            if spec.get("iterdir_fails"):
                stack.enter_context(
                    mock.patch.object(Path, "iterdir", side_effect=OSError("denied"))
                )
            result = _call(audit.explicit_datasets, root / spec["named"], root)
        return _scrub(result, str(root))


# --------------------------------------------------------------------------
# near duplicates
# --------------------------------------------------------------------------


def _drow(index: int, text: str) -> audit.DatasetRow:
    return audit.DatasetRow(index=index, input_key="input", normalized_input=text,
                            expected_key=None, expected=None, split=None)


def _near_duplicate_cases() -> dict[str, list[audit.DatasetRow]]:
    base = " ".join(f"w{j}" for j in range(20))
    swapped = " ".join(f"w{j}" for j in range(19)) + " other"
    common = [_drow(i, f"shared word{i} item{i}") for i in range(60)]
    return {
        "empty": [],
        "close_pair": [_drow(0, base), _drow(1, swapped), _drow(2, "unrelated words")],
        "identical_texts": [_drow(0, base), _drow(1, base)],
        "far_pair": [_drow(0, "a b c"), _drow(1, "a x y")],
        "reversed_indexes": [_drow(5, base), _drow(2, swapped)],
        "common_token_only": common,
        "empty_texts": [_drow(0, ""), _drow(1, "")],
    }


# --------------------------------------------------------------------------
# probe payload, differences and partial values
# --------------------------------------------------------------------------


def _payload_cases() -> dict[str, dict]:
    return {
        "no_datasets": {"files": {}, "reports": []},
        "text_gold": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "expected_output": "Paris"},
             {"input": "b", "expected_output": "paris "},
             {"input": "c", "expected_output": "London"}])}, "reports": [("d.jsonl", 3)]},
        "number_gold": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "answer": 1}, {"input": "b", "answer": 1},
             {"input": "c", "answer": 2.5}, {"input": "d", "answer": 40}])},
            "reports": [("d.jsonl", 4)]},
        "boolean_gold": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "label": True}, {"input": "b", "label": False}])},
            "reports": [("d.jsonl", 2)]},
        "object_gold": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "target": {"x": 1, "y": "A"}},
             {"input": "b", "target": {"x": 1, "y": "a"}},
             {"input": "c", "target": {"x": 2, "y": "b"}}])}, "reports": [("d.jsonl", 3)]},
        "array_gold": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "expected": [1, 2, 3]}, {"input": "b", "expected": [1, 2]},
             {"input": "c", "expected": [4, 5, 6, 7]}])}, "reports": [("d.jsonl", 3)]},
        "mixed_kinds_first_pair_wins": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "output": 1}, {"input": "b", "output": "x"},
             {"input": "c", "output": "y"}, {"input": "d", "output": 2},
             {"input": "e", "output": "z"}])}, "reports": [("d.jsonl", 5)]},
        "unusable_gold": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "expected_output": None}, {"input": "b"},
             {"input": "c", "expected_output": ""}, {"input": "d", "expected_output": {}},
             {"input": "e", "expected_output": []}, {"input": "f", "expected_output": "only"}])},
            "reports": [("d.jsonl", 6)]},
        "unusable_nan": {"files": {"d.jsonl": '{"input": "a", "answer": NaN}\n'
                                   '{"input": "b", "answer": 1}\n'},
                         "reports": [("d.jsonl", 2)]},
        "largest_file_first": {"files": {
            "small.jsonl": _jsonl([{"input": "a", "answer": "s1"},
                                   {"input": "b", "answer": "s2"}]),
            "big.jsonl": _jsonl([{"input": "a", "answer": "b1"},
                                 {"input": "b", "answer": "b2"},
                                 {"input": "c", "answer": "b3"}])},
            "reports": [("small.jsonl", 2), ("big.jsonl", 3)]},
        "missing_file_then_ok": {"files": {"ok.jsonl": _jsonl(
            [{"input": "a", "answer": "o1"}, {"input": "b", "answer": "o2"}])},
            "reports": [("gone.jsonl", 9), ("ok.jsonl", 2)]},
        "candidate_cap": {"files": {"d.jsonl": _jsonl(
            [{"input": str(i), "answer": f"v{i} words here"} for i in range(8)])},
            "reports": [("d.jsonl", 8)], "cap": 3},
        "one_value_only": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "answer": "same"}, {"input": "b", "answer": "same"}])},
            "reports": [("d.jsonl", 2)]},
        "list_partial_none": {"files": {"d.jsonl": _jsonl(
            [{"input": "a", "answer": [1]}, {"input": "b", "answer": [2]}])},
            "reports": [("d.jsonl", 2)]},
    }


def _observe_payload(spec: dict) -> dict:
    with _tmpdir() as root:
        _write(root, spec["files"])
        reports = [_report_stub(name, rows) for name, rows in spec["reports"]]
        with ExitStack() as stack:
            if "cap" in spec:
                stack.enter_context(mock.patch.object(audit, "PROBE_CANDIDATES", spec["cap"]))
            return _scrub(_call(audit.build_probe_payload, reports, root), str(root))


def _report_stub(file: str, rows: int) -> audit.DatasetReport:
    return audit.DatasetReport(
        file=file, rows=rows, input_key_counts={}, expected_key_counts={},
        missing_expected=[], exact_duplicate_groups=[], near_duplicate_pairs=[],
        split_counts={}, holdout_rows=0, holdout_overlap=[], label_counts={}, findings=[],
    )


DIFFERENCE_PAIRS: dict[str, tuple[object, object]] = {
    "bools_equal": (True, True),
    "bool_vs_int": (True, 1),
    "int_vs_bool": (0, False),
    "numbers": (1, 3.5),
    "number_overflow": (10**400, 0.5),
    "number_inf": (1e308, -1e308),
    "dicts": ({"a": 1, "b": "X", "c": 3}, {"a": 1, "b": "x", "d": 4}),
    "dicts_same": ({"a": "Hi  there"}, {"a": "hi there"}),
    "lists": ([1, "A", 3], ["1", "a", 3, 4, 5]),
    "lists_same": (["a"], ["A"]),
    "texts_case": ("Hello  World", "hello world"),
    "texts_differ": ("yes", "no"),
    "text_vs_number": ("1", 1),
    "dict_vs_list": ({"a": 1}, [1]),
    "none_vs_none": (None, None),
}

PARTIAL_PAIRS: dict[str, tuple[object, object]] = {
    "text_tokens": ("the right answer", "wrong"),
    "text_upper": ("PARIS", "x"),
    "text_one_char_lower": ("x", "y"),
    "text_long_lower": ("paris", "x"),
    "list_short": ([1], [2]),
    "list_empty_bad": ([1, 2], []),
    "list_ok": ([1, 2, 3], [4, 5]),
    "list_same_last": ([1, 2], [3, 2]),
    "list_equals_bad": ([9, 2], [9, 2]),
    "list_vs_text": ([1, 2], "x"),
    "dict_shared_key": ({"a": 1, "b": 2}, {"a": 1, "b": 3}),
    "dict_no_shared": ({"a": 1}, {"b": 1}),
    "dict_candidate_is_bad": ({"a": 1}, {"a": 2}),
    "dict_second_key": ({"a": 1, "b": 2, "c": 3}, {"a": 5, "b": 9}),
    "dict_vs_list": ({"a": 1}, [1]),
    "number": (1, 2),
    "boolean": (True, False),
}


# --------------------------------------------------------------------------
# probe results: validation, metrics, summary
# --------------------------------------------------------------------------


def _probe_payloads() -> dict[str, object]:
    good = {"good": [1.0, 1.0], "partial": [0.5], "bad": [0.0]}
    return {
        "not_a_dict": [1, 2],
        "empty": {},
        "ran_only": {"ran": True},
        "ran_not_bool": {"ran": 1},
        "full": {"ran": True, "network_blocked": False, "network_guard": "active",
                 "stage": "call", "scores": good, "errors": []},
        "unknown_guard_and_stage": {"ran": False, "network_guard": "maybe",
                                    "stage": "elsewhere", "extra": 1},
        "guard_not_string": {"ran": False, "network_guard": 3, "stage": 4,
                             "network_blocked": "no"},
        "scores_not_dict": {"ran": True, "scores": [1]},
        "scores_unknown_case": {"ran": True, "scores": {"good": [1], "worse": [0]}},
        "scores_not_numbers": {"ran": True, "scores": {"good": ["1"]}},
        "scores_bool": {"ran": True, "scores": {"good": [True]}},
        "scores_overflow": {"ran": True, "scores": {"good": [10**400]}},
        "scores_nonfinite": {"ran": True, "scores": {"good": [float("inf")]}},
        "scores_too_many": {"ran": True, "scores": {"good": [1.0] * 1001}},
        "scores_not_list": {"ran": True, "scores": {"good": 1.0}},
        "scores_empty_dict": {"ran": True, "scores": {}, "errors": []},
        "errors_mixed": {"ran": True, "scores": {"good": [1.0], "partial": [], "bad": []},
                         "errors": [
                             {"error_type": "KeyError", "error_site": "s.py:3", "case": "bad"},
                             {"error_type": "bad type!", "error_site": "no line", "case": "x"},
                             {"error_type": 5, "case": "partial", "non_finite": True},
                             {"non_finite": "yes"},
                         ]},
        "errors_with_bad_item": {"ran": True, "errors": [{"error_type": "E"}, "text"]},
        "errors_too_many": {"ran": True, "errors": [{}] * 101},
        "errors_not_list": {"ran": True, "errors": {"a": 1}},
        "top_level_fault": {"ran": False, "stage": "load", "error_type": "ImportError",
                            "error_site": "mod.py:12"},
        "top_level_fault_bad_site": {"ran": False, "stage": "load",
                                     "error_type": "ImportError", "error_site": 7},
        "top_level_site_without_type": {"ran": False, "error_site": "mod.py:1"},
        "missing_ran_with_extras": {"stage": "load", "x": 1, "y": 2},
        "ran_false_no_scores": {"ran": False, "stage": "timeout"},
        "ran_with_partial_none_case": {"ran": True, "scores": {"good": [1.0], "bad": [0.0]},
                                       "errors": []},
        "ran_good_short": {"ran": True, "scores": {"good": [1.0], "partial": [0.5],
                                                   "bad": [0.0]}, "errors": []},
        "ran_no_good": {"ran": True, "scores": {"good": [], "partial": [0.5], "bad": [0.0]},
                        "errors": []},
        "ran_no_partial": {"ran": True, "scores": {"good": [1.0, 1.0], "partial": [],
                                                   "bad": [0.0]}, "errors": []},
        "ran_two_bad": {"ran": True, "scores": {"good": [1.0, 1.0], "partial": [0.5],
                                                "bad": [0.0, 0.1]}, "errors": []},
        "ran_with_errors": {"ran": True, "scores": {"good": [1.0], "partial": [],
                                                    "bad": []},
                            "errors": [{"error_type": "ValueError", "case": "partial"}]},
        "ran_without_errors_key": {"ran": True, "scores": good},
    }


EVIDENCE_ARGS: dict[str, tuple[object, dict]] = {
    "default": (None, {}),
    "two_repeats": (2, {}),
    "one_repeat": (1, {}),
    "no_partial": (2, {"partial_probed": False}),
    "zero_repeats": (0, {}),
    "bool_repeats": (True, {}),
    "float_repeats": (2.0, {}),
}


def _probe_results() -> dict[str, dict | None]:
    def ran(good=(1.0, 1.0), partial=(0.5,), bad=(0.0,), errors=(), **extra) -> dict:
        result = {"ran": True, "scores": {"good": list(good), "partial": list(partial),
                                          "bad": list(bad)},
                  "errors": [dict(error) for error in errors], "payload_source": "dataset"}
        result.update(extra)
        return result

    raised = {"error_type": "KeyError", "error_site": "s.py:4", "case": "bad"}
    return {
        "none": None,
        "blocked": {"ran": True, "network_blocked": True},
        "failed_load": {"ran": False, "stage": "load", "error_type": "ImportError",
                        "error_site": "m.py:2"},
        "failed_launch_no_type": {"ran": False, "stage": "launch"},
        "failed_timeout": {"ran": False, "stage": "timeout"},
        "failed_unknown_stage": {"ran": False, "stage": "mystery"},
        "failed_no_stage": {"ran": False},
        "ready": ran(),
        "ready_synthetic": ran(payload_source="synthetic"),
        "ready_no_partial": ran(partial=(), partial_probed=False),
        "unstable": ran(good=(1.0, 0.5, 1.0)),
        "misordered": ran(good=(0.2, 0.2), bad=(0.9,)),
        "partial_above_good": ran(partial=(1.5,)),
        "partial_below_bad": ran(partial=(-1.0,)),
        "tied": ran(good=(1.0,), partial=(1.0,), bad=(1.0,)),
        "non_finite": ran(good=(float("inf"),)),
        "nan_scores": ran(good=(float("nan"),)),
        "incomplete_no_errors": ran(bad=()),
        "dropped_keys": ran(dropped_keys=2),
        "partial_extra_when_not_probed": ran(partial_probed=False),
        "errors_with_scores": ran(bad=(), errors=[raised]),
        "errors_good_case": ran(good=(1.0,), errors=[{"error_type": "E", "case": "good"}]),
        "errors_all_no_scores": ran(good=(), partial=(), bad=(), errors=[raised]),
        "errors_no_scores_non_finite": ran(good=(), partial=(), bad=(),
                                           errors=[{"non_finite": True, "case": "good"}]),
        "errors_mixed_kinds": ran(bad=(), errors=[raised, {"non_finite": True,
                                                           "case": "bad"}]),
        "errors_synthetic": ran(bad=(), errors=[raised], payload_source="synthetic"),
        "no_scores_key": {"ran": True, "errors": [raised]},
        "scores_none": {"ran": True, "scores": None, "errors": None},
        "misordered_synthetic": ran(good=(0.2, 0.2), bad=(0.9,), payload_source="synthetic"),
        "empty_good_with_errors": ran(good=(), errors=[{"error_type": "E", "case": "good"}]),
        "non_finite_no_partial": ran(good=(float("-inf"),), partial=(),
                                     partial_probed=False),
    }


# --------------------------------------------------------------------------
# venv and key lookups
# --------------------------------------------------------------------------


VENV_CASES: dict[str, dict] = {
    "no_cfg": {"cfg": None, "site": ["3.11"]},
    "isolated": {"cfg": "home = /usr/bin\ninclude-system-site-packages = false\n",
                 "site": ["3.12", "3.10"]},
    "inherits_with_version": {
        "cfg": "home = {base}/bin\ninclude-system-site-packages = TRUE\nversion = 3.12.4\n",
        "site": ["3.12"],
        "base": ["lib/python3.12/site-packages", "lib/python3.12/dist-packages",
                 "lib/python3/dist-packages", "local/lib/python3.12/dist-packages"],
    },
    "inherits_with_version_info": {
        "cfg": "home={base}/bin\ninclude-system-site-packages=true\nversion_info=3.11.9.final.0\n",
        "base": ["lib/python3.11/site-packages", "lib/python3.12/site-packages"],
    },
    "inherits_without_version": {
        "cfg": "home = {base}/bin\ninclude-system-site-packages = true\nnot a pair\n",
        "base": ["lib/python3.10/site-packages", "lib/python3.13/dist-packages"],
        "user": ["python3.10/site-packages", "python3.12/site-packages"],
    },
    "inherits_short_version": {
        "cfg": "include-system-site-packages = true\nversion = 3\n",
    },
    "inherits_without_home": {
        "cfg": "include-system-site-packages = true\nversion = 3.9.1\n",
    },
    "cfg_is_directory": {"cfg": "<dir>"},
}


def _observe_venv(spec: dict) -> dict:
    with _tmpdir() as tmp:
        venv = tmp / "venv"
        venv.mkdir()
        base = tmp / "base"
        home = tmp / "home"
        for version in spec.get("site", []):
            (venv / "lib" / f"python{version}" / "site-packages").mkdir(parents=True)
        for rel in spec.get("base", []):
            (base / rel).mkdir(parents=True)
        for rel in spec.get("user", []):
            (home / ".local" / "lib" / rel).mkdir(parents=True)
        cfg = spec["cfg"]
        if cfg == "<dir>":
            (venv / "pyvenv.cfg").mkdir()
        elif cfg is not None:
            (venv / "pyvenv.cfg").write_text(cfg.format(base=base), encoding="utf-8")
        with mock.patch.object(audit.Path, "home", return_value=home):
            return _scrub(_call(audit.venv_site_paths, venv), str(tmp))


KEY_CASES: dict[str, dict] = {
    "nothing": {"files": {}, "env": {}},
    "environment_only": {"files": {}, "env": {"OPENAI_API_KEY": "v", "TRAIGENT_API_KEY": "v",
                                              "UNRELATED": "v"}},
    "env_files": {
        "files": {
            ".env": "OPENAI_API_KEY=x\n  export GROQ_API_KEY = y\n# COHERE_API_KEY=z\n",
            ".env.local": "TRAIGENT_API_KEY=1\nOPENAI_API_KEY_OLD=2\n",
            ".env.empty": "NOTHING=1\n",
            ".envrc": "OPENAI_API_KEY=3\n",
            "sub/.env": "GEMINI_API_KEY=4\n",
            "config.env": "COHERE_API_KEY=5\n",
        },
        "env": {"MISTRAL_API_KEY": "v"},
    },
    "unreadable_env_file": {"files": {".env.d/x": "a directory named like an env file"},
                            "env": {}},
}


def _observe_keys(spec: dict) -> dict:
    with _tmpdir() as root:
        _write(root, spec["files"])
        files = sorted(path for path in root.rglob("*")
                       if path.is_file() or path.name.startswith(".env"))
        with mock.patch.dict(os.environ, spec["env"], clear=True):
            return _scrub(_call(audit.key_presence, root, files), str(root))


# --------------------------------------------------------------------------
# knob wiring and the area cards
# --------------------------------------------------------------------------


def _krec(name: str, status: str) -> dict:
    return {"name": name, "values": [], "values_readable": True, "status": status,
            "file": "agent.py", "line": 3}


def _erec(function: str, knobs: list[dict], note: str | None = None) -> dict:
    return {"function": function, "file": "agent.py", "line": 7, "knobs": knobs,
            "config_space_note": note}


READ, MAYBE, UNREAD = audit.KNOB_READ, audit.KNOB_MAYBE, audit.KNOB_UNREAD


def _wiring_cases() -> dict[str, object]:
    many_unread = [_krec(f"k{i}", UNREAD) for i in range(5)] + [_krec("r", READ)]
    many_maybe = [_krec(f"m{i}", MAYBE) for i in range(4)]
    return {
        "none": [],
        "read": [_erec("f", [_krec("model", READ)])],
        "blank": [_erec("f", [_krec("model", READ)]), _erec("g", [])],
        "blank_with_note_is_not_blank": [_erec("g", [], note="n")],
        "all_unread": [_erec("f", [_krec("a", UNREAD), _krec("b", UNREAD)])],
        "partly_unread_many": [_erec("f", many_unread)],
        "partly_unread_one": [_erec("f", [_krec("a", UNREAD), _krec("b", READ)])],
        "not_inventoried": [_erec("f", [_krec("a", READ)], note="space unreadable")],
        "possibly_read_many": [_erec("f", many_maybe)],
        "possibly_read_three": [_erec("f", many_maybe[:3] + [_krec("r", READ)])],
        "order_blank_before_unread": [_erec("f", [_krec("a", UNREAD)]), _erec("g", [])],
        "bad_status": [_erec("f", [_krec("a", "sometimes")])],
        "status_not_string": [_erec("f", [_krec("a", 3)])],
        "missing_status_key": [_erec("f", [{"name": "a"}])],
        "entry_without_knobs_key": [{"function": "f"}],
    }


def _knob(name: str, status: str, readable: bool = True, line: int = 3) -> audit.Knob:
    return audit.Knob(name=name, values=["v"] if readable else [], values_readable=readable,
                      status=status, file="agent.py", line=line)


def _entry(function: str, knobs: list[audit.Knob], note: str | None = None,
           line: int = 7) -> audit.EntryPoint:
    return audit.EntryPoint(function=function, file="agent.py", line=line,
                            knobs=list(knobs), config_space_note=note)


def _inventory(entries: list[audit.EntryPoint] = (), *, notes: list[str] = (),
               unparsed: list[str] = (), total: int = 3, scanned: int = 3,
               sites: list[dict] = (), scorers: list = (), skipped: list = ()
               ) -> audit.PythonInventory:
    inventory = audit.PythonInventory(files_scanned=scanned, files_total=total)
    inventory.entry_points = list(entries)
    inventory.notes = list(notes)
    inventory.files_unparsed = list(unparsed)
    inventory.llm_call_sites = list(sites)
    inventory.scorers = list(scorers)
    inventory.skipped_scorers = list(skipped)
    return inventory


def _agent_cases() -> dict[str, audit.PythonInventory]:
    site = {"function": "ask", "file": "agent.py", "line": 4, "providers": ["openai"]}
    return {
        "nothing": _inventory(),
        "call_sites": _inventory(sites=[dict(site, line=i) for i in range(7)],
                                 notes=["scan note"]),
        "read": _inventory([_entry("f", [_knob("model", READ)])]),
        "read_with_unparsed": _inventory([_entry("f", [_knob("model", READ)])],
                                         unparsed=["bad.py", "worse.py"]),
        "read_over_file_cap": _inventory([_entry("f", [_knob("model", READ)])],
                                         total=audit.MAX_PYTHON_FILES + 1),
        "all_unread": _inventory([_entry("f", [_knob("a", UNREAD), _knob("b", UNREAD)])]),
        "partly_unread": _inventory([_entry("f", [_knob("a", UNREAD), _knob("b", READ)])]),
        "blank": _inventory([_entry("f", [])]),
        "not_inventoried": _inventory([_entry("f", [], note="space note")]),
        "possibly_read": _inventory([_entry("f", [_knob("a", MAYBE), _knob("b", MAYBE)])]),
        "unreadable_values": _inventory([_entry("f", [_knob("a", READ, readable=False)])]),
        "mixed": _inventory([
            _entry("f", [_knob("a", UNREAD), _knob("b", MAYBE, readable=False)], note="n"),
            _entry("g", [], line=20),
            _entry("h", [_knob("c", READ)], line=30),
        ], notes=["first note"]),
    }


def _ds_report(file: str, rows: int, **extra: object) -> audit.DatasetReport:
    report = _report_stub(file, rows)
    report.expected_key_counts = {"expected_output": rows}
    report.split_counts = {"holdout": 30, "train": 40}
    for key, value in extra.items():
        setattr(report, key, value)
    return report


def _dataset_area_cases() -> dict[str, tuple]:
    plain = _ds_report("data.jsonl", 70)
    detailed = _ds_report(
        "d.jsonl", 12, expected_key_counts={}, split_counts={},
        notes=["declared by name"], findings=["only 12 rows"],
        missing_expected=[1, 2, 3, 4, 5, 6], exact_duplicate_groups=[[0, 3], [1, 2]],
        near_duplicate_pairs=[[4, 5]],
    )
    many = [_ds_report(f"f{i:02d}.jsonl", 40) for i in range(audit.MAX_DATASETS_IN_CARD + 2)]
    return {
        "skipped_only": ([], 3, ["note a"], ["x.jsonl could not be read"]),
        "none_at_all": ([], 0, [], []),
        "none_with_notes": ([], 4, ["looked at the first 2"], []),
        "ok": ([plain], 1, [], []),
        "detailed": ([detailed], 2, ["scan note"], ["y.csv could not be parsed"]),
        "many": (many, len(many), [], []),
        "ok_with_skip": ([plain], 2, [], ["z.json is not an array"]),
    }


def _cand(function: str, kind: str = "deterministic", line: int = 1,
          signals: list[str] = ()) -> audit.ScorerCandidate:
    return audit.ScorerCandidate(function=function, file="scorer.py", line=line, kind=kind,
                                 signals=list(signals), parameters=["output", "expected"])


def _scorer_area_cases() -> dict[str, tuple]:
    det = _cand("score")
    skipped = [audit.SkippedScorer(function="_s", file="s.py", line=2,
                                   reason=audit.SKIP_PRIVATE)]
    many = [_cand(f"score_{i}", line=i) for i in range(audit.MAX_SCORERS_IN_CARD + 3)]
    judges = [_cand("judge", "llm-judge", 5, ["imports openai"]),
              _cand("run", "executing", 9, ["uses subprocess"]),
              _cand("mix", "hybrid", 12, ["imports openai", "uses subprocess"]),
              _cand("odd", "unknown-kind", 15)]
    results = _probe_results()
    cases: dict[str, tuple] = {
        "none_found": (_inventory(), None, None, None),
        "none_found_with_skipped": (_inventory(skipped=skipped), None, None, None),
        "refusal_without_scorers": (_inventory(), None, None, "refused: judge"),
        "refusal": (_inventory(scorers=judges), None, None, "refused: judge"),
        "no_probe": (_inventory(scorers=many + judges, skipped=skipped), None, None, None),
        "probe_without_probed": (_inventory(scorers=[det]), results["ready"], None, None),
    }
    for name in ("ready", "ready_synthetic", "blocked", "failed_load", "unstable",
                 "misordered", "errors_with_scores", "non_finite", "misordered_synthetic",
                 "errors_all_no_scores", "ready_no_partial", "incomplete_no_errors"):
        cases[f"probe/{name}"] = (_inventory(scorers=[det]), results[name], det, None)
    return cases


def _setup_area_cases() -> dict[str, tuple]:
    keys_none = {"names_set_in_environment": [], "names_declared_in_env_files": {}}
    keys_env = {"names_set_in_environment": ["OPENAI_API_KEY", "TRAIGENT_API_KEY"],
                "names_declared_in_env_files": {}}
    keys_file = {"names_set_in_environment": [],
                 "names_declared_in_env_files": {"z/.env": ["B"], ".env": ["A", "C"]}}
    sdk_ok = {"interpreter": "/venv/bin/python", "traigent_version": "0.30.0"}
    return {
        "all_ok": (sdk_ok, keys_env, "ignored", ["gpt-a", "gpt-b"]),
        "not_installed": ({"interpreter": "/py", "traigent_version": None},
                          keys_file, "ignored", []),
        "error_type": ({"interpreter": "/py", "traigent_version": None,
                        "error_type": "OSError"}, keys_none, "no .env file", []),
        "read_base": ({"interpreter": "/py", "traigent_version": None,
                       "read_base_installation": True}, keys_env, "unknown", []),
        "tracked_env": (sdk_ok, keys_file, "not ignored", ["m"]),
        "no_keys": (sdk_ok, keys_none, "ignored", []),
        "missing_version_key": ({"interpreter": "/py"}, keys_env, "ignored", []),
    }


# --------------------------------------------------------------------------
# the network guard (in a child process: it replaces socket entry points)
# --------------------------------------------------------------------------


GUARD_CHILD = r"""
import json, socket, sys
sys.path.insert(0, sys.argv[1])
import _socket
if sys.argv[3] == "trimmed":
    for module, names in ((socket, ("socketpair", "gethostbyname")),
                          (_socket, ("dup", "create_connection"))):
        for name in names:
            if hasattr(module, name):
                delattr(module, name)
if sys.argv[2] == "scorer_probe":
    import scorer_probe as module
else:
    import audit_project as module
before = {f"{m.__name__}.{n}": getattr(m, n, None)
          for m in (socket, _socket)
          for n in ("socket", "socketpair", "fromfd", "dup", "create_connection",
                    "getaddrinfo", "gethostbyname")}
module.install_network_guard()
after = {}
for key, old in before.items():
    owner, name = key.split(".")
    new = getattr(socket if owner == "socket" else _socket, name, None)
    if new is None:
        after[key] = "absent"
    elif new is old:
        after[key] = "unchanged"
    else:
        after[key] = getattr(new, "__name__", type(new).__name__)
calls = {}
for label, call in (("socket", lambda: socket.socket()),
                    ("connect", lambda: socket.create_connection(("localhost", 9))),
                    ("raw", lambda: _socket.socket())):
    try:
        call()
        calls[label] = "returned"
    except Exception as exc:
        calls[label] = [type(exc).__name__, str(exc)]
print(json.dumps({"replaced": after, "calls": calls,
                  "verify": getattr(module, "verify_network_guard", lambda: None)()},
                 sort_keys=True))
"""


def _observe_guard(module: str, variant: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-I", "-c", GUARD_CHILD, str(SCRIPTS_DIR), module, variant],
        capture_output=True, text=True, timeout=60, check=False,
    )
    return {"returncode": completed.returncode, "stdout": completed.stdout,
            "stderr_empty": completed.stderr == ""}


# --------------------------------------------------------------------------
# build_report, with the sandbox, probe, SDK and git lookups replaced
# --------------------------------------------------------------------------


AGENT = """
import openai
import traigent

@traigent.optimize(configuration_space={"model": ["gpt-a", "gpt-b"], "temperature": [0.0, 0.7],
                                        "engine": ["e1"]})
def answer(question, model, temperature):
    return openai.chat(question, model, temperature)
"""

SCORER = """
def score(output, expected):
    return float(output == expected)
"""

JUDGE = """
import openai

def score_judge(output, expected):
    return openai.grade(output, expected)
"""

HELPER = """
def compare_answers(output, expected):
    return 1.0
"""


def _project(extra: dict[str, str | bytes] | None = None) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {
        "agent.py": AGENT,
        "scorer.py": SCORER,
        "eval/tuning.jsonl": _jsonl(_rows(40)),
        "eval/holdout.jsonl": _jsonl(_rows(31, start=100)),
        "traigent-runs/run1/holdout.jsonl": _jsonl(_rows(2)),
        "traigent-runs/run1/tuning.csv": "input\nq\n",
        "traigent-runs/run1/agent.py": "def score(output, expected):\n    return 1\n",
        ".env": "OPENAI_API_KEY=redacted\n",
    }
    files.update(extra or {})
    return files


def _report_cases() -> dict[str, dict]:
    return {
        "discovery_single_deterministic": {"files": _project()},
        "discovery_two_deterministic": {"files": _project({"other.py": SCORER})},
        "discovery_no_deterministic": {"files": _project({"scorer.py": JUDGE})},
        "explicit_dataset": {"files": _project(), "dataset": "eval/tuning.jsonl"},
        "selected_in_inventory": {"files": _project(), "scorer": "scorer.py:score"},
        "selected_absolute": {"files": _project(), "scorer": "<root>/scorer.py:score"},
        "selected_by_name_outside_inventory": {
            "files": _project({"lib/helpers.py": HELPER}),
            "scorer": "lib/helpers.py:compare_answers",
        },
        "selected_skipped_scorer": {
            "files": _project({"lib/helpers.py": "def _score(output, expected):\n"
                                                 "    return 1.0\n"}),
            "scorer": "lib/helpers.py:_score",
        },
        "selected_missing_function": {"files": _project(), "scorer": "scorer.py:nothing"},
        "selected_unparsable_module": {"files": _project({"bad.py": "def (\n"}),
                                       "scorer": "bad.py:score"},
        "selected_judge_refused": {"files": _project({"judge.py": JUDGE}),
                                   "scorer": "judge.py:score_judge"},
        "selected_without_colon": {"files": _project(), "scorer": "scorer.py"},
        "selected_without_function": {"files": _project(), "scorer": "scorer.py:"},
        "isolated_bwrap": {"files": _project(),
                           "isolation": ("isolated (bwrap)", "bwrap",
                                         ["bwrap", "--unshare-net"], ["--"])},
        "synthetic_payload": {"files": {"agent.py": AGENT, "scorer.py": SCORER}},
        "empty_project": {"files": {}},
    }


def _observe_report(spec: dict) -> dict:
    calls: list[list] = []

    def fake_probe(interpreter, scorer, root, payload, repeats, isolation):
        calls.append(["probe", interpreter, asdict(scorer), str(root), list(payload),
                      repeats, list(isolation)])
        good, partial, bad, source = payload
        return {"ran": True, "scores": {"good": [1.0] * repeats,
                                        "partial": [] if partial is None else [0.5],
                                        "bad": [0.0]},
                "errors": [], "payload_source": source,
                "partial_probed": partial is not None, "dropped_keys": 0}

    def fake_sdk(interpreter):
        calls.append(["sdk", interpreter])
        return {"interpreter": interpreter, "traigent_version": "0.30.0",
                "read_base_installation": False}

    def fake_ignored(root):
        calls.append(["ignored", str(root)])
        return "ignored"

    isolation = spec.get("isolation", (audit.GUARD_PYTHON, "", [], []))
    with _tmpdir() as tmp:
        root = tmp / "project"
        root.mkdir()
        _write(root, spec["files"])
        scorer = spec.get("scorer")
        if scorer is not None:
            scorer = scorer.replace("<root>", str(root))
        args = argparse.Namespace(dataset=(str(root / spec["dataset"])
                                           if spec.get("dataset") else None),
                                  scorer=scorer, repeats=3, json_out=None)
        patches = [
            mock.patch.object(audit, "detect_isolation", lambda: isolation),
            mock.patch.object(audit, "run_scorer_probe", fake_probe),
            mock.patch.object(audit, "read_sdk_version", fake_sdk),
            mock.patch.object(audit, "env_file_ignored", fake_ignored),
            mock.patch.object(audit, "project_interpreter", lambda root: "/fake/python"),
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "redacted"}, clear=True),
        ]
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            result = _call(audit.build_report, root, args, "active")
        if "returned" in result:
            result["card"] = audit.render_card(result["returned"])
        result["calls"] = _jsonable(calls)
        return _scrub(result, str(tmp))


# --------------------------------------------------------------------------
# collection, the record, and the tests
# --------------------------------------------------------------------------


def collect() -> dict[str, object]:
    observed: dict[str, object] = {}
    for name, source in SOURCES.items():
        observed[f"source/{name}"] = _observe_source(source)
    for name, text in EXPRESSIONS.items():
        observed[f"expression/{name}"] = _observe_expression(text)
    for name, files in _scan_cases().items():
        observed[f"scan_python/{name}"] = _observe_scan(name, files, None)
    observed["scan_python/over_file_cap"] = _observe_scan(
        "over_file_cap", _scan_cases()["all_sources"], 3)
    observed.update(_load_row_observations())
    for name, spec in _explicit_layouts().items():
        observed[f"explicit_datasets/{name}"] = _observe_explicit(spec)
    for name, rows in _near_duplicate_cases().items():
        observed[f"near_duplicate_pairs/{name}"] = _call(audit.near_duplicate_pairs, rows)
    for name, spec in _payload_cases().items():
        observed[f"build_probe_payload/{name}"] = _observe_payload(spec)
    for name, (good, other) in DIFFERENCE_PAIRS.items():
        observed[f"answer_difference/{name}"] = _call(audit.answer_difference, good, other)
    for name, (good, bad) in PARTIAL_PAIRS.items():
        observed[f"partial_value/{name}"] = _call(audit.partial_value, good, bad)
    for name, payload in _probe_payloads().items():
        observed[f"validate_probe_payload/{name}"] = _call(
            audit.validate_probe_payload, copy.deepcopy(payload))
        for arg_name, (repeats, kwargs) in EVIDENCE_ARGS.items():
            observed[f"validate_probe_evidence/{name}/{arg_name}"] = _call(
                audit.validate_probe_evidence, copy.deepcopy(payload), repeats, **kwargs)
    for name, result in _probe_results().items():
        observed[f"probe_metrics/{name}"] = _call(audit.probe_metrics, copy.deepcopy(result))
        if result is not None:
            observed[f"summarize_probe/{name}"] = _call(
                audit.summarize_probe, copy.deepcopy(result))
    for name, spec in VENV_CASES.items():
        observed[f"venv_site_paths/{name}"] = _observe_venv(spec)
    for name, spec in KEY_CASES.items():
        observed[f"key_presence/{name}"] = _observe_keys(spec)
    for name, records in _wiring_cases().items():
        observed[f"knob_wiring/{name}"] = _call(audit.knob_wiring, copy.deepcopy(records))
    for name, inventory in _agent_cases().items():
        observed[f"agent_area/{name}"] = _call(audit.agent_area, inventory)
    for name, args in _dataset_area_cases().items():
        observed[f"dataset_area/{name}"] = _call(audit.dataset_area, *args)
    for name, args in _scorer_area_cases().items():
        observed[f"scorer_area/{name}"] = _call(audit.scorer_area, *args)
    for name, args in _setup_area_cases().items():
        observed[f"setup_area/{name}"] = _call(audit.setup_area, *args)
    for variant in ("full", "trimmed"):
        observed[f"install_network_guard/audit_project/{variant}"] = _observe_guard(
            "audit_project", variant)
    for name, spec in _report_cases().items():
        observed[f"build_report/{name}"] = _observe_report(spec)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
