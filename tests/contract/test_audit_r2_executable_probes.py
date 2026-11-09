"""Executable probes for four round-2 skill defects (skills-improve-2026-11-09).

Markdown syntax checks cannot see these; each probe runs the code the skill teaches.

* a reference-free judge that is swapped in for ``build_judge_prompt`` must work when the
  row has no gold answer (``expected is None``) and refuse a blank rubric;
* row ids are assigned at dataset prep and checked: ``_example_id`` rejects a row without an
  id, and ``check_row_ids`` flags duplicates (content hashing cannot separate identical rows);
* the resume recipe keeps the first run's explicit local ``algorithm`` (a default ``auto``
  function resolves to connected execution without it, and resume then refuses);
* no skill claims the ``traigent`` CLI ignores ``.env`` or tells the user to source it.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from .test_audit_326_comparator_case import FENCE_RE, _python_block, _run_driver

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
EVAL_BUILD = SKILLS / "traigent-eval-build" / "SKILL.md"
TEMPLATES = SKILLS / "traigent-eval-build" / "references" / "evaluator-templates.md"
RESUME = SKILLS / "traigent-optimize-run" / "references" / "resume-local-run.md"


def _blocks(path: Path, marker: str) -> list[str]:
    return [b for b in FENCE_RE.findall(path.read_text(encoding="utf-8")) if marker in b]


def _function_namespace(block: str, name: str) -> Any:
    """Compile one top-level function from a taught block and return it (no SDK imports run)."""
    node = next(
        n for n in ast.parse(block).body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    namespace: dict[str, Any] = {}
    exec(compile(ast.Module([node], []), f"<{name}>", "exec"), namespace)
    return namespace[name]


def _row(metadata: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(input_data={"q": "same"}, expected_output="a", metadata=metadata)


# --- 1. reference-free judge on expected=None ------------------------------------------------


def test_reference_free_judge_runs_with_no_gold_and_refuses_a_blank_rubric(
    tmp_path: Path,
) -> None:
    body = """
    install_replies(lambda model, messages: '{"score": 0.8, "reason": "ok"}')
    write_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
    ns = load_block(sys.argv[1])
    build = ns["build_reference_free_judge_prompt"]

    try:
        build("summary", None, {"text": "source"})
        blank = "no error"
    except ValueError:
        blank = "refused"

    ns["TASK_RUBRIC"] = "Reward faithful, concise summaries."
    prompt = json.loads(build("summary", None, {"text": "source"}))

    # The documented swap: same call site, new builder, a row with no gold answer.
    ns["build_judge_prompt"] = build
    example = type("Ex", (), {
        "input_data": {"question": "q"}, "expected_output": None, "metadata": {"id": "r1"}})()
    budget = ns["JudgeBudget"](cap_usd=1.0, per_call_usd=0.5)
    result = ns["llm_judge_evaluator"](lambda **kw: "summary", {}, example, budget=budget)
    emit({"blank": blank, "prompt": prompt, "success": result.success,
          "quality": result.metrics["quality"], "error": result.error_message})
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, "def llm_judge_evaluator"), body)
    assert result["blank"] == "refused"
    assert "Reward faithful, concise summaries." in result["prompt"]["rubric"]
    assert result["prompt"]["source"] == {"text": "source"}
    assert (result["success"], result["quality"], result["error"]) == (True, 0.8, None)


# --- 2. stable unique row ids ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "count"), [(EVAL_BUILD, 1), (TEMPLATES, 3)], ids=["SKILL.md", "evaluator-templates.md"]
)
def test_example_id_helper_requires_a_row_id(path: Path, count: int) -> None:
    blocks = _blocks(path, "def _example_id")
    assert len(blocks) == count
    for block in blocks:
        assert "sha256" not in block, "ids must be assigned at dataset prep, not hashed from content"
        helper = _function_namespace(block, "_example_id")
        assert helper(_row({"id": "row-00001"})) == "row-00001"
        assert helper(_row({"id": 7})) == "7"
        for missing in ({}, {"id": None}, {"id": ""}):
            with pytest.raises(ValueError, match="no 'id'"):
                helper(_row(missing))


def _prep_helpers() -> tuple[Any, Any]:
    (block,) = _blocks(EVAL_BUILD, "def check_row_ids")
    namespace: dict[str, Any] = {}
    exec(compile(block, "<dataset-prep>", "exec"), namespace)
    return namespace["assign_row_ids"], namespace["check_row_ids"]


def test_dataset_prep_flags_duplicate_and_missing_ids_and_assigns_unique_ones(
    tmp_path: Path,
) -> None:
    assign, check = _prep_helpers()
    identical = {"input": {"q": "same"}, "output": "a"}
    dataset = tmp_path / "qa.jsonl"
    dataset.write_text(
        "".join(json.dumps(r) + "\n" for r in [identical, identical, {**identical, "id": "keep"}])
    )
    with pytest.raises(ValueError, match="no 'id'"):
        check(str(dataset))
    assign(str(dataset))
    check(str(dataset))  # identical rows now carry distinct ids
    ids = [json.loads(line)["id"] for line in dataset.read_text().splitlines()]
    assert len(set(ids)) == 3 and "keep" in ids
    before = dataset.read_text()
    assign(str(dataset))
    assert dataset.read_text() == before, "existing ids must never be renumbered"

    dataset.write_text(
        "".join(json.dumps({**identical, "id": "dup"}) + "\n" for _ in range(2))
    )
    with pytest.raises(ValueError, match="repeats id 'dup'"):
        check(str(dataset))


# --- 3. resume keeps the local algorithm -----------------------------------------------------


def test_resume_recipe_repeats_the_explicit_local_algorithm() -> None:
    (block,) = _blocks(RESUME, "resume_from=saved_name")
    calls = [
        n
        for n in ast.walk(ast.parse(block))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "optimize_sync"
    ]
    assert len(calls) == 1
    keywords = {k.arg: k.value for k in calls[0].keywords}
    assert {"algorithm", "resume_from"} <= keywords.keys()
    algorithm = keywords["algorithm"]
    assert isinstance(algorithm, ast.Constant) and algorithm.value in {"grid", "random"}


# --- 4. the CLI reads .env ---------------------------------------------------------------------

CLAIMS = (
    re.compile(r"CLI\s+does\s+not\s+read\s+`?\.env", re.I),
    re.compile(r"Shell commands do not read\s+`?\.env", re.I),
    re.compile(r"CLI command[^.\n]{0,80}does not read\s+`?\.env", re.I),
    re.compile(r"set -a;\s*\.\s+\./\.env"),
)


def test_no_skill_says_the_cli_ignores_dotenv_or_tells_the_user_to_source_it() -> None:
    offenders = []
    for path in sorted(SKILLS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern in CLAIMS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    assert not offenders, offenders
