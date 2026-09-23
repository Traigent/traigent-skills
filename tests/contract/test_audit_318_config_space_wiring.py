"""Boost-agent: the taught configuration space holds only knobs the function reads.

Traigent/traigent-skills#318. Step 7 of the playbook spread the removed
``recommend_configuration_space()`` dict (``recommendations["configuration_space"]``),
and the instrument recipe admitted every ``Choices`` row ``generate_config``
returned, including knobs the decorated function never reads. Every trial that
varies an unread knob is a silent no-op that still costs money.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from .extract import _iter_fenced_blocks

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "traigent-boost-agent" / "SKILL.md"
RECIPE = ROOT / "skills" / "traigent-boost-agent" / "references" / "instrument-recipe.md"


def _python_blocks(path: Path) -> list[str]:
    blocks = _iter_fenced_blocks(path.read_text(encoding="utf-8").splitlines())
    return [block.text for block in blocks if block.language == "python"]


def _recipe_before_after() -> tuple[str, str]:
    text = RECIPE.read_text(encoding="utf-8")
    before = _python_blocks_between(text, "## Before", "## After")
    after = _python_blocks_between(text, "## After", "## Environment")
    return before, after


def _python_blocks_between(text: str, start: str, end: str) -> str:
    section = text.split(start, 1)[1].split(end, 1)[0]
    blocks = _iter_fenced_blocks(section.splitlines())
    python = [block.text for block in blocks if block.language == "python"]
    assert len(python) == 1, f"expected one python block between {start!r} and {end!r}"
    return python[0]


def _config_keys_read(source: str) -> set[str]:
    """Keys read from a config mapping: ``cfg["k"]`` and ``cfg.get("k", ...)``."""
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "cfg"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "cfg"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.add(node.args[0].value)
    return keys


def _stage_tuned_params(source: str) -> set[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.keyword) and node.arg == "stage_tuned_params":
            return {elt.value for elt in node.value.elts}
    raise AssertionError("no stage_tuned_params in the recipe's After block")


def _offline_env(home: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith("_API_KEY") and key not in {"TRAIGENT_MOCK_LLM", "CI", "GITHUB_ACTIONS"}
    }
    env.update(
        {
            "HOME": str(home),
            "ENVIRONMENT": "test",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TRAIGENT_OFFLINE_MODE": "true",
            # Only so an older recipe that builds a raw client at import can be
            # imported for inspection; nothing here makes a model call.
            "OPENAI_API_KEY": "sk-test-not-a-real-key",
            "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
        }
    )
    return env


def test_no_skill_spreads_the_removed_recommendations_dict() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in sorted((ROOT / "skills").glob("**/*.md"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if 'recommendations["configuration_space"]' in line
    ]
    assert not offenders, "stale recommend_configuration_space() dict: " + ", ".join(offenders)


def test_step7_snippet_builds_a_space_from_step5_rows(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("traigent.config_generator")
    monkeypatch.setenv("TRAIGENT_OFFLINE_MODE", "true")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    before, _ = _recipe_before_after()
    agent = tmp_path / "agent.py"
    agent.write_text(before + "\n", encoding="utf-8")

    blocks = _python_blocks(SKILL)
    step5 = next(b for b in blocks if "generate_config(" in b and "suggested =" in b)
    step7 = next(b for b in blocks if "CONFIGURATION_SPACE = {" in b and "COMPOSITE.members" in b)
    step5 = step5.replace('"path/to/agent.py"', repr(str(agent))).replace(
        '"my_agent"', '"answer_question"'
    )

    namespace: dict[str, object] = {"COMPOSITE": SimpleNamespace(members={})}
    exec(compile(step5, "boost-agent Step 5", "exec"), namespace)
    exec(compile(step7, "boost-agent Step 7", "exec"), namespace)

    space = namespace["CONFIGURATION_SPACE"]
    assert isinstance(space, dict)
    assert {"model", "temperature", "candidate_count"} <= set(space)


def test_recipe_space_holds_only_knobs_the_function_reads(tmp_path: Path) -> None:
    pytest.importorskip("traigent")
    _, after = _recipe_before_after()
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "qa.jsonl").write_text(
        json.dumps({"input": {"question": "What is 2+2?"}, "output": "4"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "home").mkdir()
    agent = tmp_path / "agent.py"
    agent.write_text(after + "\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(
        textwrap.dedent(
            f"""
            import builtins, json, runpy
            builtins.retrieve_context = lambda question, **kw: ["ctx"]
            builtins.format_context = lambda chunks, **kw: "ctx"
            builtins.estimate_last_call_cost_usd = lambda: 0.0
            builtins.estimate_call_cost_usd = lambda response: 0.0
            ns = runpy.run_path({str(agent)!r}, run_name="recipe_under_test")
            print("SPACE=" + json.dumps(sorted(ns["CONFIGURATION_SPACE"])))
            """
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(runner)],
        cwd=tmp_path,
        env=_offline_env(tmp_path / "home"),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("SPACE="))
    space = set(json.loads(line.removeprefix("SPACE=")))

    read = _config_keys_read(after)
    unread = space - read
    assert not unread, f"knobs declared in CONFIGURATION_SPACE but never read: {sorted(unread)}"

    missing = _stage_tuned_params(after) - space
    assert not missing, f"stage_tuned_params not in CONFIGURATION_SPACE: {sorted(missing)}"
