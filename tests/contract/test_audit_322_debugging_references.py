"""Debugging references: exception triggers match the SDK, and YAML examples parse.

Traigent/traigent-skills#322. ``error-reference.md`` listed a non-list and an empty
``configuration_space`` as ``ConfigurationError`` triggers (the SDK raises
``ValidationError`` and a builtin ``ValueError``), ``logging-config.md`` quoted a
``ConfigurationError`` message the SDK never emits, and the CI workflow in
``mock-mode.md`` was tab-indented, so it was not valid YAML.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
import yaml

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
REFS = ROOT / "skills" / "traigent-debugging" / "references"


def _yaml_blocks() -> list[tuple[str, str]]:
    blocks = []
    for path in sorted((ROOT / "skills").glob("**/*.md")):
        for block in _iter_fenced_blocks(path.read_text(encoding="utf-8").splitlines()):
            if block.language in {"yaml", "yml"}:
                blocks.append((f"{path.relative_to(ROOT)}:{block.start_line}", block.text))
    return blocks


def test_every_yaml_fence_under_skills_parses() -> None:
    failures = []
    for where, text in _yaml_blocks():
        try:
            yaml.safe_load(textwrap.dedent(text))
        except yaml.YAMLError as exc:
            failures.append(f"{where}: {type(exc).__name__}: {str(exc).splitlines()[0]}")
    assert not failures, "fenced yaml that does not parse:\n" + "\n".join(failures)


def test_error_reference_does_not_list_space_shape_mistakes_as_configuration_error() -> None:
    text = (REFS / "error-reference.md").read_text(encoding="utf-8")
    section = text.split("### ConfigurationError", 1)[1].split("\n### ", 1)[0]
    triggers = section.split("**Common triggers**:", 1)[1].split("\n\n", 1)[0]
    assert "Non-list values" not in triggers
    assert "Empty configuration space" not in triggers


def test_space_shape_mistakes_raise_the_documented_non_configuration_errors(tmp_path, monkeypatch) -> None:
    traigent = pytest.importorskip("traigent")
    from traigent.utils.exceptions import ConfigurationError, ValidationError

    monkeypatch.chdir(tmp_path)
    (tmp_path / "eval_data.jsonl").write_text('{"input": "q1", "output": "a"}\n', encoding="utf-8")
    with pytest.raises(ValidationError) as non_list:
        traigent.optimize(eval_dataset="eval_data.jsonl", configuration_space={"model": "gpt-4o-mini"})(
            lambda x: x
        )
    assert not isinstance(non_list.value, ConfigurationError)
    with pytest.raises(ValueError) as empty:
        traigent.optimize(eval_dataset="eval_data.jsonl", configuration_space={})(lambda x: x)
    assert not isinstance(empty.value, ConfigurationError)


def test_logging_config_quotes_a_configuration_error_the_sdk_emits(tmp_path, monkeypatch) -> None:
    traigent = pytest.importorskip("traigent")
    from traigent.utils.exceptions import ConfigurationError

    text = (REFS / "logging-config.md").read_text(encoding="utf-8")
    quoted = set(re.findall(r"traigent\.utils\.exceptions\.ConfigurationError: (.+)", text))
    assert quoted, "logging-config.md quotes no ConfigurationError message"

    monkeypatch.chdir(tmp_path)
    (tmp_path / "eval_data.jsonl").write_text('{"input": "q1", "output": "a"}\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as exc:
        traigent.optimize(
            eval_dataset="eval_data.jsonl",
            configuration_space={"model": ["a", "b"]},
            offline=True,
            algorithm="bayesian",
        )(lambda x: x)
    assert quoted == {str(exc.value)}, (quoted, str(exc.value))
