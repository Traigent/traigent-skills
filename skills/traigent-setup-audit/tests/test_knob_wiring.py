"""Unit tests for the static knob-wiring detection.

A knob declared in the configuration space and never read by the decorated body
cannot change the output, so every trial that varies it is spend with no effect.
The detection must find that case, must not report a parameter as unread, and
must not be fooled by the declaration itself.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load_audit_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("audit_project")


audit = _load_audit_module()


def _entries(source: str):
    return audit.collect_entry_points(ast.parse(source), "agent.py")


WIRED = '''
import traigent


@traigent.optimize(configuration_space={"model": ["a"], "temperature": [0.0, 1.0]})
def run(question, model, temperature):
    return f"{model}/{temperature}/{question}"
'''

UNWIRED = '''
import traigent


@traigent.optimize(configuration_space={"model": ["a"], "temperature": [0.0, 1.0]})
def run(question, model):
    return f"{model}/{question}"
'''

LITERAL_READ = '''
import traigent


@traigent.optimize(configuration_space={"temperature": [0.0, 1.0]})
def run(question, **options):
    return options["temperature"]
'''

MAPPING_READ = '''
import traigent


@traigent.optimize(configuration_space={"depth": [1, 2]})
def run(question, config):
    return config[SOME_KEY]
'''

ALIAS_IMPORT = '''
from traigent import optimize


@optimize(configuration_space={"model": ["a"]})
def run(question, model):
    return model
'''


def test_every_knob_read_as_a_parameter_is_reported_read() -> None:
    entries = _entries(WIRED)
    assert len(entries) == 1
    assert {knob.name: knob.status for knob in entries[0].knobs} == {
        "model": "read",
        "temperature": "read",
    }


def test_a_declared_knob_the_body_never_reads_is_reported_with_its_line() -> None:
    entries = _entries(UNWIRED)
    statuses = {knob.name: knob.status for knob in entries[0].knobs}
    assert statuses["model"] == "read"
    assert statuses["temperature"] == "declared, never read"
    temperature = next(k for k in entries[0].knobs if k.name == "temperature")
    assert temperature.file == "agent.py"
    assert temperature.line == 5


def test_the_declaration_itself_does_not_count_as_a_read() -> None:
    """Walking the decorator would make every declared knob look read."""
    parameters, literals, dynamic = audit.function_read_surface(
        ast.parse(UNWIRED).body[-1]
    )
    assert "temperature" not in literals
    assert "temperature" not in parameters
    assert dynamic is False


def test_a_string_literal_read_counts() -> None:
    statuses = {knob.name: knob.status for knob in _entries(LITERAL_READ)[0].knobs}
    assert statuses["temperature"] == "read"


def test_an_unfollowable_mapping_read_is_reported_as_possible_not_as_unread() -> None:
    statuses = {knob.name: knob.status for knob in _entries(MAPPING_READ)[0].knobs}
    assert statuses["depth"] == "possibly read through a config mapping"


def test_the_from_import_alias_form_is_detected() -> None:
    entries = _entries(ALIAS_IMPORT)
    assert len(entries) == 1
    assert entries[0].function == "run"


def test_an_undecorated_function_is_not_an_entry_point() -> None:
    assert _entries("def run(question):\n    return question\n") == []
