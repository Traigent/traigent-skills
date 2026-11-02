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


# traigent-skills#472: the SDK accepts a knob declared inline as a decorator
# keyword (``model=Choices([...])``) and boost-agent teaches that shape.

INLINE_ONLY = '''
import traigent
from traigent import Choices, Range


@traigent.optimize(
    objectives=["accuracy"],
    model=Choices(["a", "b"]),
    temperature=Range(0.0, 1.0),
    top_k=(1, 5),
)
def run(question, model, temperature):
    return f"{model}/{temperature}/{question}"
'''

INLINE_BY_NAME = '''
import traigent
from traigent import Choices

MODELS = Choices(["a", "b"])


@traigent.optimize(model=MODELS)
def run(question, model):
    return model
'''

INLINE_UNRESOLVABLE = '''
import traigent

from knobs import make_model_knob


@traigent.optimize(objectives=["accuracy"], model=make_model_knob())
def run(question, model):
    return model
'''

INLINE_SPLAT = '''
import traigent
from knobs import KNOBS


@traigent.optimize(**KNOBS)
def run(question, model):
    return model
'''

NON_KNOB_KEYWORDS_ONLY = '''
import traigent


@traigent.optimize(objectives=["accuracy"], eval_dataset="data.jsonl", max_trials=5)
def run(question):
    return question
'''


def test_inline_choices_and_range_keywords_are_inventoried_as_knobs() -> None:
    entry = _entries(INLINE_ONLY)[0]
    assert {knob.name: knob.status for knob in entry.knobs} == {
        "model": "read",
        "temperature": "read",
        "top_k": "declared, never read",
    }
    assert entry.config_space_note is None
    model = next(knob for knob in entry.knobs if knob.name == "model")
    assert (model.values, model.values_readable) == (["a", "b"], True)
    assert model.line == 8


def test_an_inline_knob_passed_by_module_constant_is_inventoried() -> None:
    entry = _entries(INLINE_BY_NAME)[0]
    assert [knob.name for knob in entry.knobs] == ["model"]
    assert entry.config_space_note is None


def test_an_inline_keyword_the_audit_cannot_read_is_unread_never_absent() -> None:
    for source in (INLINE_UNRESOLVABLE, INLINE_SPLAT):
        entry = _entries(source)[0]
        assert entry.knobs == []
        assert entry.config_space_note is not None
        assert "not inventoried" in entry.config_space_note


def test_decorator_options_are_not_mistaken_for_inline_knobs() -> None:
    entry = _entries(NON_KNOB_KEYWORDS_ONLY)[0]
    assert entry.knobs == []
    assert entry.config_space_note is None


SCALAR_OPTIONS = '''
import traigent


@traigent.optimize(objectives=["accuracy"], cost_limit=2, plateau_epsilon=0.01, tie_breakers=None)
def run(question):
    return question
'''


def test_scalar_literal_decorator_options_are_not_reported_as_unread_knobs() -> None:
    entry = _entries(SCALAR_OPTIONS)[0]
    assert entry.knobs == []
    assert entry.config_space_note is None


RUNTIME_OVERRIDES_BY_CONSTANT = '''
import traigent

BUDGET = 2.0
EPSILON = 0.01


@traigent.optimize(
    configuration_space={"model": ["a", "b"]},
    cost_limit=BUDGET,
    plateau_epsilon=EPSILON,
    plateau_window=3,
    metric_limit=100,
)
def run(question, model):
    return f"{model}/{question}"
'''


def test_runtime_override_keywords_given_by_constant_are_not_reported_unread() -> None:
    entry = _entries(RUNTIME_OVERRIDES_BY_CONSTANT)[0]
    assert [knob.name for knob in entry.knobs] == ["model"]
    assert entry.config_space_note is None
