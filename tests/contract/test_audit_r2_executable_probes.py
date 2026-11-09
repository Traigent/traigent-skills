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
import os
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
    write_prepared_rows("qa.jsonl", [{"input": {"question": "q"}, "output": "a"}])
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
    (block,) = _blocks(EVAL_BUILD, "def assign_row_ids")
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
    with pytest.raises(ValueError, match="no top-level 'id'"):
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


# --- round 3 wording cues --------------------------------------------------------------------


def test_round3_cues_are_present() -> None:
    quick = (SKILLS / "traigent-setup-quickstart" / "SKILL.md").read_text(encoding="utf-8")
    assert "In an existing project, still deliver one" in quick and "dry_run.py" in quick
    curate = (SKILLS / "traigent-dataset-curate" / "SKILL.md").read_text(encoding="utf-8")
    assert "Illustrative arithmetic, not a threshold" in curate
    assert "Dedupe before splitting" in curate
    flat = " ".join(
        (SKILLS / "traigent-analyze-guidance" / "references" / "preflight.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "traigent sync <session_id>" in flat and "Never use the whole-store `--all`" in flat
    build = EVAL_BUILD.read_text(encoding="utf-8")
    assert "Every trial fails or scores 0.0?" in build and "not 'tuple'" in build


# --- round 4: whole-dataset, effective-id validation before any model call ---------------------

CURATE = SKILLS / "traigent-dataset-curate" / "SKILL.md"


def _check_copies() -> list[tuple[str, Any]]:
    """Every taught check_row_ids: the SKILL.md prep block, its Tier 4 block, and the templates."""
    found = []
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def check_row_ids"):
            found.append((path.name, _function_namespace(block, "check_row_ids")))
    return found


def _normalised_sources() -> set[str]:
    sources = set()
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def check_row_ids"):
            node = next(
                n for n in ast.parse(block).body
                if isinstance(n, ast.FunctionDef) and n.name == "check_row_ids"
            )
            sources.add(ast.dump(node))
    return sources


def _check_with_json_and_path() -> list[Any]:
    helpers = []
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def check_row_ids"):
            node = next(
                n for n in ast.parse(block).body
                if isinstance(n, ast.FunctionDef) and n.name == "check_row_ids"
            )
            namespace: dict[str, Any] = {"json": json, "Path": Path, "os": os}
            exec(compile(ast.Module([node], []), "<check>", "exec"), namespace)
            helpers.append(namespace["check_row_ids"])
    return helpers


def test_every_custom_template_validates_the_dataset_with_one_identical_check() -> None:
    assert len(_normalised_sources()) == 1
    # Tier 4 block + prep block in SKILL.md, plus the three id-using templates.
    assert len(_check_with_json_and_path()) == 5
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def _example_id"):
            tree = ast.parse(block)
            calls = [
                n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "check_row_ids"
            ]
            decorated = [
                n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.decorator_list
            ]
            assert calls and decorated and min(calls) < min(decorated), "check must run at import"


EFFECTIVE_CASES = {
    "nested duplicates, no top-level": ([{"metadata": {"id": "shared"}}, {"metadata": {"id": "shared"}}], "no top-level 'id'"),
    "distinct top-level, shared nested": ([{"id": "a", "metadata": {"id": "shared"}}, {"id": "b", "metadata": {"id": "shared"}}], "conflicting"),
    "nested null override": ([{"id": "a", "metadata": {"id": None}}], "conflicting"),
    "nested empty override": ([{"id": "a", "metadata": {"id": ""}}], "conflicting"),
    "conflicting locations": ([{"id": "a", "metadata": {"id": "b"}}], "conflicting"),
    "nested-only id": ([{"metadata": {"id": "r1"}}], "no top-level 'id'"),
    "repeated top-level": ([{"id": "a"}, {"id": "a"}], "repeats id"),
    "missing": ([{"input": 1}], "no top-level 'id'"),
    "empty top-level": ([{"id": ""}], "no top-level 'id'"),
}


@pytest.mark.parametrize("case", sorted(EFFECTIVE_CASES))
def test_check_row_ids_validates_the_effective_id(case: str, tmp_path: Path) -> None:
    rows, message = EFFECTIVE_CASES[case]
    dataset = tmp_path / "d.jsonl"
    dataset.write_text("".join(json.dumps({"input": "x", **r}) + "\n" for r in rows))
    for check in _check_with_json_and_path():
        with pytest.raises(ValueError, match=message):
            check(str(dataset))


def test_check_row_ids_accepts_distinct_effective_ids(tmp_path: Path) -> None:
    dataset = tmp_path / "d.jsonl"
    rows = [{"id": "a"}, {"id": "b", "metadata": {"id": "b"}}, {"id": "c", "metadata": {"split": "x"}}]
    dataset.write_text("".join(json.dumps({"input": "x", **r}) + "\n" for r in rows))
    for check in _check_with_json_and_path():
        check(str(dataset))


def _published_rows() -> list[dict[str, Any]]:
    text = CURATE.read_text(encoding="utf-8")
    start = text.index("`eval/tuning.jsonl`")
    block = re.search(r"```json\n(.*?)```", text[start:], re.S).group(1)
    return [json.loads(line) for line in block.splitlines() if line.strip()]


def test_published_curate_rows_carry_ids() -> None:
    text = CURATE.read_text(encoding="utf-8")
    rows = [
        json.loads(line)
        for line in text.splitlines()
        if line.startswith('{"id"') or line.startswith('{"input"')
    ]
    assert rows and all(row.get("id") for row in rows)
    assert len({row["id"] for row in rows}) == len(rows)


def test_idless_published_example_fails_before_any_model_call_unless_prepped(
    tmp_path: Path,
) -> None:
    published = _published_rows()
    idless = [{k: v for k, v in row.items() if k != "id"} for row in published]
    body = f"""
    install_replies(lambda model, messages: '{{"score": 0.8, "reason": "ok"}}')
    rows = {idless!r}
    write_rows("qa.jsonl", rows)              # exactly as published minus the id
    outcome = {{}}
    try:
        load_block(sys.argv[1])
        outcome["skipped_prep"] = "loaded"
    except ValueError as exc:
        outcome["skipped_prep"] = str(exc)
    outcome["calls_after_skipped_prep"] = len(CALLS)

    write_prepared_rows("qa.jsonl", rows)      # the documented prep step
    ns = load_block(sys.argv[1])
    outcome["prepped"] = "loaded"
    outcome["calls_after_prep"] = len(CALLS)
    emit(outcome)
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, "def llm_judge_evaluator"), body)
    assert "no top-level 'id'" in result["skipped_prep"], result
    assert result["calls_after_skipped_prep"] == 0
    assert result["prepped"] == "loaded" and result["calls_after_prep"] == 0

    (tmp_path / "ok").mkdir()
    ready = f"""
    write_rows("qa.jsonl", {published!r})      # the published rows, ids included, no prep
    load_block(sys.argv[1])
    emit({{"loaded": True, "calls": len(CALLS)}})
    """
    ok = _run_driver(tmp_path / "ok", _python_block(TEMPLATES, "def llm_judge_evaluator"), ready)
    assert ok == {"loaded": True, "calls": 0}


# --- round 4: wording that must not return --------------------------------------------------------


def test_round4_wording() -> None:
    build = EVAL_BUILD.read_text(encoding="utf-8")
    assert "a connected run can reject duplicate ids" not in build
    assert "outcome_matrix.py:293-303" in build and "metadata_helpers.py:637-645" in build
    assert "built-in flows" in build.lower() or "Built-in" in build
    text2sql = (SKILLS / "traigent-recipe-text2sql" / "SKILL.md").read_text(encoding="utf-8")
    assert "premium, a mid-priced and a cheap model" not in text2sql
    assert "hold the high-impact structural levers" not in text2sql.lower()
    assert "weight accuracy first" not in text2sql
    guidance = (SKILLS / "traigent-analyze-guidance" / "SKILL.md").read_text(encoding="utf-8")
    assert "a first-run search is 12" not in guidance
    curate = CURATE.read_text(encoding="utf-8")
    assert "inside the noise" not in curate
    assert "Is the Delta Real?" in curate and "approximate 95%" in curate


# --- round 5: one dataset path, top-level ids on every SDK, utf-8 ---------------------------------


def _helper_nodes() -> dict[str, set[str]]:
    dumps: dict[str, set[str]] = {}
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def check_row_ids"):
            for node in ast.parse(block).body:
                if isinstance(node, ast.FunctionDef) and node.name in {"check_row_ids", "dataset_path"}:
                    dumps.setdefault(node.name, set()).add(ast.dump(node))
    return dumps


def test_dataset_path_and_check_are_identical_in_every_copy() -> None:
    dumps = _helper_nodes()
    assert {k: len(v) for k, v in dumps.items()} == {"check_row_ids": 1, "dataset_path": 1}


def test_every_text_io_in_the_id_helpers_names_utf8() -> None:
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def check_row_ids"):
            tree = ast.parse(block)
            for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                       and n.name in {"check_row_ids", "assign_row_ids"}):
                calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                         and isinstance(c.func, ast.Attribute) and c.func.attr in {"read_text", "write_text"}]
                assert calls
                for call in calls:
                    assert any(k.arg == "encoding" and getattr(k.value, "value", None) == "utf-8"
                               for k in call.keywords), ast.unparse(call)


def test_templates_pass_the_same_resolved_path_to_check_and_eval_dataset() -> None:
    for path in (EVAL_BUILD, TEMPLATES):
        for block in _blocks(path, "def _example_id"):
            tree = ast.parse(block)
            check_args = [ast.unparse(c.args[0]) for c in ast.walk(tree)
                          if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "check_row_ids"]
            eval_args = [ast.unparse(k.value) for c in ast.walk(tree) if isinstance(c, ast.Call)
                         for k in c.keywords if k.arg == "eval_dataset"]
            assert check_args == ["DATASET"] and eval_args == ["DATASET"], (check_args, eval_args)


def test_dataset_root_differing_from_cwd_validates_the_file_the_sdk_loads(tmp_path: Path) -> None:
    body = """
    import os
    root = Path("sdk_root"); root.mkdir()
    (root / "eval").mkdir()
    bad = [{"input": {"question": "q"}, "output": "a"}]          # no ids
    good = [{"id": "r1", "input": {"question": "q"}, "output": "a"}]
    source = Path(sys.argv[1]).read_text(encoding="utf-8")        # NOT rewritten: real resolution
    outcome = {}

    def attempt(label, cwd_rows, root_rows):
        write_rows("qa.jsonl", cwd_rows)                           # ./eval/qa.jsonl
        (root / "eval" / "qa.jsonl").write_text("".join(json.dumps(r) + "\\n" for r in root_rows))
        os.environ["TRAIGENT_DATASET_ROOT"] = str(root.resolve())
        namespace = {"__name__": "template_under_test"}
        try:
            exec(compile(source, "template_under_test", "exec"), namespace)
            outcome[label] = "loaded:" + namespace["DATASET"]
        except ValueError as exc:
            outcome[label] = "refused:" + str(exc)

    attempt("root_good_cwd_bad", bad, good)
    attempt("root_bad_cwd_good", good, bad)
    outcome["root"] = str(root.resolve())
    emit(outcome)
    """
    result = _run_driver(tmp_path, _python_block(TEMPLATES, "def llm_judge_evaluator"), body)
    root = result["root"]
    assert result["root_good_cwd_bad"] == f"loaded:{root}/eval/qa.jsonl"
    assert result["root_bad_cwd_good"].startswith("refused:") and root in result["root_bad_cwd_good"]


def _assign_and_check() -> tuple[Any, Any]:
    (block,) = _blocks(EVAL_BUILD, "def assign_row_ids")
    namespace: dict[str, Any] = {}
    exec(compile(block, "<dataset-prep>", "exec"), namespace)
    return namespace["assign_row_ids"], namespace["check_row_ids"]


def test_prep_promotes_a_nested_id_and_both_sdk_shapes_expose_it(tmp_path: Path) -> None:
    assign, check = _assign_and_check()
    dataset = tmp_path / "qa.jsonl"
    rows = [
        {"input": "q1", "output": "a", "metadata": {"id": "keep-me", "split": "x"}},
        {"input": "q2", "output": "a"},
        {"input": "q3", "output": "a", "id": "row-00001"},
    ]
    dataset.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="no top-level 'id'"):
        check(str(dataset))
    assign(str(dataset))
    check(str(dataset))
    prepared = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    assert prepared[0]["id"] == "keep-me", "a valid nested id is promoted, not renumbered"
    assert len({r["id"] for r in prepared}) == 3 and prepared[2]["id"] == "row-00001"

    (block,) = _blocks(EVAL_BUILD, "def _example_id")
    helper = _function_namespace(block, "_example_id")
    for row in prepared:
        # SDK >= 0.28: a row's own metadata object is merged over the top-level keys.
        merged = {**{k: v for k, v in row.items() if k not in {"input", "output", "metadata"}},
                  **row.get("metadata", {})}
        # SDK 0.24-0.27: the nested object stays nested; only top-level keys are metadata.
        legacy = {k: v for k, v in row.items() if k not in {"input", "output"}}
        for metadata in (merged, legacy):
            assert helper(SimpleNamespace(input_data={}, expected_output=None, metadata=metadata)) == row["id"]


# --- round 6: paired-delta snippet, fail-closed gate, offline disclosure ------------------------


def _paired_delta() -> Any:
    text = (SKILLS / "traigent-analyze-results" / "SKILL.md").read_text(encoding="utf-8")
    (block,) = [b for b in FENCE_RE.findall(text) if "def paired_delta" in b]
    namespace: dict[str, Any] = {"__name__": "paired_delta_snippet"}
    exec(compile(block, "<paired_delta>", "exec"), namespace)
    return namespace["paired_delta"]


def test_paired_delta_snippet_reports_wins_losses_and_exact_sign_test() -> None:
    paired = _paired_delta()
    out = paired([1, 0, 1, 1, 0, 1, 0, 1], [1, 1, 1, 1, 1, 1, 0, 1])
    assert (out["wins"], out["losses"], out["ties"]) == (2, 0, 6)
    assert out["sign_test_p"] == pytest.approx(0.5)  # 2 * C(2,0) / 2**2
    assert out["mean_delta"] == pytest.approx(0.25)
    low, high = out["ci95"]
    assert low <= out["mean_delta"] <= high

    lopsided = paired([0.0] * 12, [1.0] * 12)
    assert (lopsided["wins"], lopsided["losses"]) == (12, 0)
    assert lopsided["sign_test_p"] == pytest.approx(2 / 2**12)

    balanced = paired([1, 0, 1, 0], [0, 1, 0, 1])
    assert (balanced["wins"], balanced["losses"], balanced["sign_test_p"]) == (2, 2, 1.0)
    assert paired([1, 1], [1, 1])["sign_test_p"] == 1.0
    assert paired([0] * 5, [1] * 5)["sign_test_p"] == pytest.approx(0.0625)  # exact, not significant
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            paired([0.0, 1.0], [bad, 1.0])
        with pytest.raises(ValueError, match="finite"):
            paired([bad, 1.0], [0.0, 1.0])
    with pytest.raises(ValueError, match="finite"):
        paired([float("inf")], [float("inf")])  # inf - inf is NaN
    with pytest.raises(ValueError):
        paired([1.0], [])


def test_gate_script_fails_closed_on_anything_but_promote() -> None:
    script = (SKILLS / "traigent-ci-safety-gate" / "references" / "gate-workflow.md").read_text(encoding="utf-8")
    assert 'if decision.decision != "promote":' in script
    assert 'decision.decision == "reject":' not in script
    skill = (SKILLS / "traigent-ci-safety-gate" / "SKILL.md").read_text(encoding="utf-8")
    assert 'if decision.decision != "promote":' in skill
    assert "no_decision" in skill and "optimistic" in skill


def test_offline_disclosure_is_taught() -> None:
    text = (SKILLS / "traigent-optimize-run" / "SKILL.md").read_text(encoding="utf-8")
    assert "When you run offline, tell the user" in text
    assert "LITELLM_LOCAL_MODEL_COST_MAP=True" in text


def test_interval_is_labelled_approximate_and_demoted_below_the_sign_test() -> None:
    text = (SKILLS / "traigent-analyze-results" / "SKILL.md").read_text(encoding="utf-8")
    assert "approximate percentile-bootstrap 95% interval" in text
    assert "lead with\n`sign_test_p`" in text or "lead with `sign_test_p`" in " ".join(text.split())


# --- round 7: aggregate intervals must not be read as a ranking verdict ---------------------------


def _analyze_block(marker: str) -> dict[str, Any]:
    text = (SKILLS / "traigent-analyze-results" / "SKILL.md").read_text(encoding="utf-8")
    (block,) = [b for b in FENCE_RE.findall(text) if marker in b]
    namespace: dict[str, Any] = {"__name__": "analyze_snippet"}
    exec(compile(block, "<analyze>", "exec"), namespace)
    return namespace


def test_paired_comparison_separates_configs_whose_wilson_intervals_overlap() -> None:
    wilson = _analyze_block("def wilson")["wilson"]
    paired = _analyze_block("def paired_delta")["paired_delta"]
    a = [1] * 60 + [0] * 40
    b = [1] * 70 + [0] * 30  # B fixes 10 examples A got wrong and breaks none
    a_hi, b_lo = wilson(60, 100)[1], wilson(70, 100)[0]
    assert a_hi > b_lo  # per-config intervals overlap
    out = paired(a, b)
    assert (out["wins"], out["losses"]) == (10, 0)
    assert out["sign_test_p"] < 0.01
    assert out["ci95"][0] > 0
    text = (SKILLS / "traigent-analyze-results" / "SKILL.md").read_text(encoding="utf-8")
    assert "ranking among\n   them is unresolved" not in text
    assert "overlapping per-config intervals do not" in text


def test_optimize_run_does_not_require_varied_outputs_for_real_inference() -> None:
    text = (SKILLS / "traigent-optimize-run" / "SKILL.md").read_text(encoding="utf-8")
    assert "outputs vary between trials" not in text
    assert "Identical outputs\n   across trials can be a real deterministic run" in text


# --- round 8: raw-client dry run and question/answer dataset conversion ---------------------------


def test_raw_client_dry_run_and_dataset_conversion_are_taught() -> None:
    quick = (SKILLS / "traigent-setup-quickstart" / "SKILL.md").read_text(encoding="utf-8")
    decorator = (SKILLS / "traigent-setup-decorator" / "SKILL.md").read_text(encoding="utf-8")
    for text in (quick, decorator):
        assert "If the agent uses a raw provider client" in text
        assert "litellm.completion" in text and "dry_run.py" in text
        assert "Never make the first test a real paid run" in text
        assert "no `__main__` block starts a paid run by default" in text
    assert "openai.OpenAI = FakeOpenAI" in quick
    assert "TRAIGENT_STRICT_COST_ACCOUNTING" not in quick.split("def __init__")[0].split("# dry_run.py")[-1]
    assert "Existing rows with other keys" in quick
    assert "Missing 'input' (or 'input_data') field" in decorator


def _dry_run_template() -> str:
    text = (SKILLS / "traigent-setup-quickstart" / "SKILL.md").read_text(encoding="utf-8")
    (block,) = [b for b in FENCE_RE.findall(text) if "openai.OpenAI = FakeOpenAI" in b]
    return block


def _write_dry_run_project(root: Path, agent_source: str) -> None:
    (root / "agent.py").write_text(agent_source, encoding="utf-8")
    rows = [{"input": {"question": f"q{i}"}, "output": f"a{i}"} for i in range(4)]
    (root / "qa_traigent.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (root / "dry_run.py").write_text(_dry_run_template(), encoding="utf-8")


_RAW_CLIENT_AGENT = """
import os
import traigent
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url="http://127.0.0.1:9/v1")
{import_time}

@traigent.optimize(
    eval_dataset="qa_traigent.jsonl",
    objectives=["accuracy", "cost"],
    configuration_space={{"model": ["gpt-4o-mini", "gpt-4o"]}},
)
def answer(question: str) -> str:
    resp = client.chat.completions.create(
        model=traigent.get_config()["model"], messages=[{{"role": "user", "content": question}}]
    )
    return resp.choices[0].message.content.strip()
"""


def _run_dry_run(root: Path, extra_env: dict[str, str]) -> Any:
    import subprocess
    import sys

    pytest.importorskip("openai")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TRAIGENT_")}
    env.update({"PYTHONPATH": str(root), "HOME": str(root), **extra_env})
    return subprocess.run(
        [sys.executable, "dry_run.py"], cwd=root, env=env, capture_output=True, text=True, timeout=300
    )


def test_stub_dry_run_completes_with_a_cost_limit_and_strict_accounting_on(tmp_path: Path) -> None:
    _write_dry_run_project(tmp_path, _RAW_CLIENT_AGENT.format(import_time=""))
    done = _run_dry_run(tmp_path, {"TRAIGENT_RUN_COST_LIMIT": "1"})
    assert done.returncode == 0, done.stderr[-2000:]
    assert "max_trials=2 reached" in (done.stdout + done.stderr)
    assert "{'model':" in done.stdout


def test_stub_dry_run_blocks_an_import_time_client_call(tmp_path: Path) -> None:
    call = 'WARM = client.chat.completions.create(model="gpt-4o", messages=[])'
    _write_dry_run_project(tmp_path, _RAW_CLIENT_AGENT.format(import_time=call))
    done = _run_dry_run(tmp_path, {})
    # a real client would raise APIConnectionError at 127.0.0.1:9; the fake answers instead
    assert done.returncode == 0, done.stderr[-2000:]
    assert "APIConnectionError" not in done.stderr


def test_lost_portal_sync_order_is_numbered_in_debugging_and_analyze_results() -> None:
    for name in ("traigent-debugging", "traigent-analyze-results"):
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert "traigent sync <session_id> --dry-run" in text
        assert "Never" in text and "traigent sync --all" in text
        assert "separate paid action" in text
        portal = text.index("Check the portal for that session id")
        assert portal < text.index("traigent sync <session_id> --dry-run")


def test_dry_run_template_is_restricted_to_sync_agents_and_names_the_public_alternative() -> None:
    quick = (SKILLS / "traigent-setup-quickstart" / "SKILL.md").read_text(encoding="utf-8")
    template = _dry_run_template()
    assert "SYNCHRONOUS agent" in template and "version-bound workaround" in template
    assert "do not adapt this template" in quick and "AsyncOpenAI" in quick
    assert "return `traigent.with_usage(text, total_cost=0)` at its return boundary" in quick
