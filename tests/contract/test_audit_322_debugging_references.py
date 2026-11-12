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
from packaging.version import Version

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


# The SDK rewrote this message after its 0.33.0 release (the development branch now names
# TRAIGENT_OFFLINE_MODE and says what to use instead). logging-config.md documents both
# wordings, each under its SDK version, and this test pins which one the installed SDK must emit.
OFFLINE_WORDING_0_32 = (
    "algorithm='bayesian' requires managed optimization and cannot be used with "
    "offline=True or TRAIGENT_OFFLINE=1."
)
OFFLINE_WORDING_NEWER = (
    "algorithm='bayesian' requires managed optimization and cannot be used with "
    "offline=True, TRAIGENT_OFFLINE=1 or TRAIGENT_OFFLINE_MODE=1. Use algorithm='grid' "
    "or 'random' for local-only runs, or unset the offline setting to use managed "
    "optimization."
)


def _offline_wording_for(sdk_version_label: str) -> str:
    # Released SDKs through 0.33.0 keep the older wording (v0.33.0 config/types.py); the develop
    # bucket, a development build (it reports a .devN version such as 0.33.0.dev0) and any build
    # after 0.33.0 use the newer one.
    if sdk_version_label == "develop":
        return OFFLINE_WORDING_NEWER
    version = Version(sdk_version_label)
    if version.is_devrelease or version > Version("0.33.0"):
        return OFFLINE_WORDING_NEWER
    return OFFLINE_WORDING_0_32


def test_logging_config_quotes_a_configuration_error_the_sdk_emits(
    tmp_path, monkeypatch, sdk_version_label: str
) -> None:
    traigent = pytest.importorskip("traigent")
    from traigent.utils.exceptions import ConfigurationError

    text = (REFS / "logging-config.md").read_text(encoding="utf-8")
    quoted = set(re.findall(r"traigent\.utils\.exceptions\.ConfigurationError: (.+)", text))
    assert quoted == {OFFLINE_WORDING_0_32, OFFLINE_WORDING_NEWER}, (
        "logging-config.md must quote each ConfigurationError wording under its SDK version",
        quoted,
    )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "eval_data.jsonl").write_text('{"input": "q1", "output": "a"}\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as exc:
        traigent.optimize(
            eval_dataset="eval_data.jsonl",
            configuration_space={"model": ["a", "b"]},
            offline=True,
            algorithm="bayesian",
        )(lambda x: x)
    expected = _offline_wording_for(sdk_version_label)
    assert expected in quoted, (expected, quoted)
    assert str(exc.value) == expected, (sdk_version_label, str(exc.value))
