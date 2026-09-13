"""Every place the first version reported a clean verdict it had not earned.

Each test here pins one reviewer finding: a configuration space the parser could
not read reported as absent (F5), a knob read through `**kwargs` reported as
never read (F6), "possibly read" flattened into a certainty (F7), and four caps
or parse failures that silently changed the headline number or dropped a file
(F4, F9, F10, F11). Plus a decorator from another library attributed to Traigent
(F12) and knob values the parser could not read (F15).
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS_DIR / "audit_project.py"


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()


def _entries(source: str):
    return audit.collect_entry_points(ast.parse(source), "agent.py")


def _run(root: Path, out_dir: Path, *extra: str):
    report_path = out_dir / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--json",
            str(report_path),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(report_path.read_text(encoding="utf-8")), completed.stdout


def _project(tmp_path: Path, name: str, **files: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (root / filename.replace("__", ".")).write_text(content, encoding="utf-8")
    return root


AGENT_TEMPLATE = '''
import traigent


@traigent.optimize(configuration_space={space})
def run(question, model):
    return f"{{model}} {{question}}"
'''


# --------------------------------------------------------------------------
# F5 — a configuration space the parser cannot read is not an absent one
# --------------------------------------------------------------------------


BY_NAME = '''
import traigent

SPACE = {"model": ["a", "b"], "temperature": [0.0, 1.0]}


@traigent.optimize(configuration_space=SPACE)
def run(question, model, temperature):
    return f"{model}{temperature}{question}"
'''

WRAPPED = '''
import traigent
from traigent.api.parameter_ranges import ConfigurationSpace


@traigent.optimize(configuration_space=ConfigurationSpace({"model": ["a"]}))
def run(question, model):
    return model
'''

DICT_CALL = '''
import traigent


@traigent.optimize(configuration_space=dict(model=["a"], depth=[1, 2]))
def run(question, model, depth):
    return f"{model}{depth}"
'''

UNREADABLE = '''
import traigent

from settings import load_space


@traigent.optimize(configuration_space=load_space())
def run(question, model):
    return model
'''


def test_a_module_level_constant_space_is_inventoried() -> None:
    entry = _entries(BY_NAME)[0]
    assert {knob.name: knob.status for knob in entry.knobs} == {
        "model": "read",
        "temperature": "read",
    }
    assert entry.config_space_note is None


def test_a_configuration_space_wrapper_is_unwrapped() -> None:
    entry = _entries(WRAPPED)[0]
    assert [knob.name for knob in entry.knobs] == ["model"]


def test_a_dict_call_space_is_inventoried() -> None:
    entry = _entries(DICT_CALL)[0]
    assert {knob.name for knob in entry.knobs} == {"model", "depth"}


def test_an_unreadable_space_is_reported_as_unread_not_as_absent(
    tmp_path: Path,
) -> None:
    entry = _entries(UNREADABLE)[0]
    assert entry.knobs == []
    assert entry.config_space_note is not None
    assert "the audit reads only a dict literal" in entry.config_space_note
    assert "load_space()" in entry.config_space_note

    root = _project(tmp_path, "unreadable", agent__py=UNREADABLE)
    report, card = _run(root, tmp_path / "out")
    assert "declares no configuration space" not in card
    assert "were not inventoried" in card
    assert report["areas"]["agent"]["status"] == "attention"
    assert report["next_step"]["branch"] != "b"


# --------------------------------------------------------------------------
# F6 / F7 — reads the parser cannot follow
# --------------------------------------------------------------------------


KWARGS_ITEMS = '''
import traigent


@traigent.optimize(configuration_space={"model": ["a"], "temperature": [0.0]})
def run(question, **kwargs):
    return {key: value for key, value in kwargs.items()}
'''

KWARGS_SPLAT = '''
import traigent


@traigent.optimize(configuration_space={"model": ["a"]})
def run(question, **overrides):
    return call_model(question, **overrides)
'''

GET_CONFIG = '''
import traigent


@traigent.optimize(configuration_space={"model": ["a"]})
def run(question, key):
    return traigent.get_config()[key]
'''

GET_CONFIG_LITERAL = '''
import traigent


@traigent.optimize(configuration_space={"model": ["a"]})
def run(question):
    return traigent.get_config()["model"]
'''


@pytest.mark.parametrize("source", [KWARGS_ITEMS, KWARGS_SPLAT, GET_CONFIG])
def test_a_mapping_read_is_possibly_read_never_never_read(source: str) -> None:
    entry = _entries(source)[0]
    assert entry.knobs
    assert all(knob.status == audit.KNOB_MAYBE for knob in entry.knobs), [
        (knob.name, knob.status) for knob in entry.knobs
    ]


def test_possibly_read_knobs_are_printed_and_never_flattened_to_certainty(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, "mapping", agent__py=KWARGS_ITEMS)
    report, card = _run(root, tmp_path / "out")
    assert "Every declared knob is read directly" not in card
    assert "read through a mapping the parser cannot follow" in card
    assert "knob `model` at agent.py:" in card
    assert "knob `temperature` at agent.py:" in card
    assert report["areas"]["agent"]["status"] == "attention"


def test_a_literal_key_is_a_direct_read_not_a_guess() -> None:
    """Teeth: naming the knob in the body is a read, not a "possibly read"."""
    entry = _entries(GET_CONFIG_LITERAL)[0]
    assert entry.knobs[0].status == audit.KNOB_READ


def test_a_direct_read_still_gets_the_plain_sentence(tmp_path: Path) -> None:
    """Teeth: the certainty sentence is still used when it is earned."""
    root = _project(
        tmp_path, "direct", agent__py=AGENT_TEMPLATE.format(space='{"model": ["a"]}')
    )
    _, card = _run(root, tmp_path / "out")
    assert "Every declared knob is read directly by the function body" in card


# --------------------------------------------------------------------------
# F12 — another library's decorator is not Traigent's
# --------------------------------------------------------------------------


OPTUNA = '''
import optuna

study = optuna.create_study()


@study.optimize
def run(trial):
    return trial
'''


def test_a_foreign_optimize_decorator_is_not_attributed_to_traigent() -> None:
    assert _entries(OPTUNA) == []


def test_a_traigent_alias_import_is_still_recognised() -> None:
    source = (
        "import traigent as tg\n\n\n"
        '@tg.optimize(configuration_space={"model": ["a"]})\n'
        "def run(question, model):\n"
        "    return model\n"
    )
    assert [entry.function for entry in _entries(source)] == ["run"]


# --------------------------------------------------------------------------
# F15 — knob values the parser cannot read
# --------------------------------------------------------------------------


CHOICES = '''
import traigent
from traigent.api.parameter_ranges import Choices


@traigent.optimize(configuration_space={"model": Choices("gpt-4o-mini", "claude-x")})
def run(question, model):
    return model
'''

OPAQUE_VALUES = '''
import traigent

from settings import MODELS


@traigent.optimize(configuration_space={"model": MODELS})
def run(question, model):
    return model
'''


def test_choices_positional_values_are_read() -> None:
    entry = _entries(CHOICES)[0]
    knob = entry.knobs[0]
    assert knob.values == ["gpt-4o-mini", "claude-x"]
    assert knob.values_readable is True


def test_unreadable_knob_values_are_said_to_be_unreadable(tmp_path: Path) -> None:
    entry = _entries(OPAQUE_VALUES)[0]
    assert entry.knobs[0].values_readable is False

    root = _project(tmp_path, "opaque", agent__py=OPAQUE_VALUES)
    report, card = _run(root, tmp_path / "out")
    assert "has values the audit could not read" in card
    assert report["setup"]["model_ids_declared"] == []


def test_choices_model_ids_reach_the_setup_area(tmp_path: Path) -> None:
    root = _project(tmp_path, "choices", agent__py=CHOICES)
    report, _ = _run(root, tmp_path / "out")
    assert report["setup"]["model_ids_declared"] == ["claude-x", "gpt-4o-mini"]


# --------------------------------------------------------------------------
# F4, F9, F10, F11 — every cap and skip is a printed finding
# --------------------------------------------------------------------------


def _rows(count: int, start: int = 0) -> str:
    return "".join(
        json.dumps({"input": f"question number {index} about topic {index}",
                    "expected_output": f"answer {index}"}) + "\n"
        for index in range(start, start + count)
    )


def test_the_near_duplicate_ceiling_is_a_finding_not_a_silent_pass(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(_rows(6), encoding="utf-8")
    raw = audit.load_rows(path)

    monkeypatch.setattr(audit, "NEAR_DUPLICATE_LIMIT", 100)
    under = audit.analyse_dataset(path, tmp_path, raw)
    assert not any("near-duplicate detection skipped" in f for f in under.findings)

    monkeypatch.setattr(audit, "NEAR_DUPLICATE_LIMIT", 3)
    over = audit.analyse_dataset(path, tmp_path, raw)
    assert any("near-duplicate detection skipped" in f for f in over.findings)
    assert any("over the 3-row ceiling" in f for f in over.findings)


def test_a_dataset_whose_checks_were_skipped_cannot_read_ok(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(_rows(40), encoding="utf-8")
    raw = audit.load_rows(path)
    monkeypatch.setattr(audit, "NEAR_DUPLICATE_LIMIT", 3)
    report = audit.analyse_dataset(path, tmp_path, raw)
    area = audit.dataset_area([report], 1, [], [])
    assert area["status"] == "attention"


def test_malformed_jsonl_lines_are_counted_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(_rows(12) + "{not json\n" + "{also not json\n", encoding="utf-8")
    raw = audit.load_rows(path)
    assert len(raw.rows) == 12
    assert any("2 line(s) were not valid JSON" in note for note in raw.notes)

    root = tmp_path / "project"
    root.mkdir()
    (root / "data.jsonl").write_text(
        _rows(12) + "{not json\n", encoding="utf-8"
    )
    report, card = _run(root, tmp_path / "out")
    assert "not valid JSON and were skipped" in card
    assert report["areas"]["dataset"]["status"] == "attention"
    # No scorer in this tree, so there is nothing to probe — stated rather than
    # assumed, since a probe that silently fails to load looks the same.
    assert report["scorer_probe"] is None


def test_a_row_cap_prints_the_real_total(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(_rows(25), encoding="utf-8")
    monkeypatch.setattr(audit, "MAX_ROWS", 10)
    raw = audit.load_rows(path)
    assert len(raw.rows) == 10
    assert any("read the first 10 of 25 line(s)" in note for note in raw.notes)
    report = audit.analyse_dataset(path, tmp_path, raw)
    assert any("read the first 10 of 25" in finding for finding in report.findings)


def test_a_file_over_the_byte_cap_is_named_not_vanished(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "big.jsonl").write_text(_rows(40), encoding="utf-8")
    monkeypatch.setattr(audit, "MAX_DATA_BYTES", 10)
    raw = audit.load_rows(root / "big.jsonl")
    assert raw.skipped is not None
    assert "over the 0 MiB cap" in raw.skipped
    reports, candidates, notes, skipped = audit.scan_datasets(
        [root / "big.jsonl"], root
    )
    assert reports == []
    assert skipped and skipped[0].startswith("big.jsonl is")
    area = audit.dataset_area(reports, candidates, notes, skipped)
    assert area["status"] == "attention"
    assert any("not analysed" in line for line in area["evidence"])


def test_a_python_file_cap_is_a_printed_finding(tmp_path: Path, monkeypatch) -> None:
    paths = []
    for index in range(5):
        path = tmp_path / f"mod{index}.py"
        path.write_text("def helper():\n    return 1\n", encoding="utf-8")
        paths.append(path)
    monkeypatch.setattr(audit, "MAX_PYTHON_FILES", 2)
    inventory = audit.scan_python(paths, tmp_path)
    assert inventory.files_scanned == 2
    assert any("scanned the first 2 of 5" in note for note in inventory.notes)
    area = audit.agent_area(inventory)
    assert any("scanned the first 2 of 5" in item for item in area["evidence"])


def test_a_dataset_file_cap_is_a_printed_finding(tmp_path: Path, monkeypatch) -> None:
    paths = []
    for index in range(4):
        path = tmp_path / f"data{index}.jsonl"
        path.write_text(_rows(3, index * 10), encoding="utf-8")
        paths.append(path)
    monkeypatch.setattr(audit, "MAX_DATA_FILES", 2)
    reports, candidates, notes, _ = audit.scan_datasets(paths, tmp_path)
    assert candidates == 4
    assert len(reports) == 2
    assert any("first 2 of 4" in note for note in notes)


def test_a_utf8_bom_does_not_discard_the_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    csv_path = root / "data.csv"
    csv_path.write_text(
        "input,expected_output\nwhat is the refund window,thirty days\n"
        "how do i export an invoice,from the billing page\n",
        encoding="utf-8-sig",
    )
    raw = audit.load_rows(csv_path)
    assert raw.rows and "input" in raw.rows[0]

    jsonl_path = root / "data.jsonl"
    jsonl_path.write_text(_rows(3), encoding="utf-8-sig")
    assert audit.load_rows(jsonl_path).rows

    json_path = root / "data.json"
    json_path.write_text(
        json.dumps([{"input": "a question", "expected_output": "an answer"}]),
        encoding="utf-8-sig",
    )
    assert audit.load_rows(json_path).rows

    report, _ = _run(root, tmp_path / "out")
    assert {item["file"] for item in report["datasets"]} == {
        "data.csv",
        "data.jsonl",
        "data.json",
    }
    assert report["scorer_probe"] is None
