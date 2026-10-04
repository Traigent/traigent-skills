"""``EvaluationOptions.task_type`` guidance is floored at its first release (traigent-skills#378).

The ``evaluation-task-type`` row of docs/version-matrix.md names the first SDK
whose ``EvaluationOptions`` accepts ``task_type`` (the floor); older SDKs reject
it at construction (pydantic ``extra_forbidden``). The two skills that teach the
field split their guidance by version, and the #270 rule must keep holding: an
SDK below the floor (0.27.x included) is never told to pass ``task_type``. It is
held by three checks:

- The SKILL.md text is version-conditional: a floor-and-later path pointing at
  the ``evaluation-task-type`` matrix row, and a below-the-floor "do not pass"
  path that states the ValidationError and the abstain outcome. The stale
  universal claims ("in no released version", "expected in a later SDK
  release") are gone.
- The runnable recipe lives in ``references/task-type.md``, floored in
  sync_map.yml at exactly the matrix row's ``changed_in_version``, so released
  buckets below the floor never execute it.
- The installed SDK accepts ``task_type`` iff it is at or above that floor. The
  CI buckets (0.21.3, 0.24.0, 0.27.0, 0.30.0, develop) prove only that
  0.27.0 < floor <= 0.30.0. The exact 0.28.0 boundary rests on offline
  construction probes of 0.27.0, 0.28.0, 0.29.0 and 0.30.0 recorded for #378.
- **Residual, review only:** new ``task_type`` prose outside these assertions
  is caught by review, not by this module.
"""

from __future__ import annotations

import ast
import importlib.metadata
import re
from pathlib import Path

import pytest
from packaging.version import Version

from .conftest import _sdk_version_label
from .extract import collect_runnable_file
from .test_version_matrix import POINTER_RE, _parse_matrix

SKILLS = ("traigent-eval-audit", "traigent-setup-decorator")
REFERENCE = "references/task-type.md"
FACT_ID = "evaluation-task-type"

TASK_TYPE_RE = re.compile(r"\btask_type\b")
DO_NOT_PASS_RE = re.compile(r"\bdo\s+(?:\*\*)?not(?:\*\*)?\s+pass\b", re.I)
VALIDATION_ERROR_RE = re.compile(r"ValidationError")
EXTRA_FORBIDDEN_RE = re.compile(r"Extra inputs are not\s+permitted")
ABSTAIN_RE = re.compile(r"\babstain", re.I)
STALE_CLAIMS = ("in no released version", "expected in a later SDK release")


def _floor(repo_root: Path) -> str:
    rows = {row.fact_id: row for row in _parse_matrix(repo_root)}
    assert FACT_ID in rows, f"docs/version-matrix.md has no `{FACT_ID}` row"
    return rows[FACT_ID].changed_in_version


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, whitespace collapsed (presence checks only)."""
    return [" ".join(p.split()) for p in re.split(r"\n[ \t]*\n", text) if p.strip()]


def test_task_type_guidance_is_version_conditional(repo_root: Path) -> None:
    floor = re.escape(_floor(repo_root))
    newer_sdk_re = re.compile(
        rf"{floor}\s+(?:and|or)\s+(?:later|newer|above)|since\s+{floor}|>=\s*{floor}"
    )
    older_sdk_re = re.compile(
        r"(?:below|before|older\s+than|earlier\s+than|prior\s+to|<)\s*"
        rf"(?:traigent\s+|SDK\s+)?{floor}(?!\.?\d)"
    )

    problems: list[str] = []
    for skill in SKILLS:
        rel = f"skills/{skill}/SKILL.md"
        paragraphs = _paragraphs((repo_root / rel).read_text(encoding="utf-8"))

        if not any(
            newer_sdk_re.search(p)
            and TASK_TYPE_RE.search(p)
            and FACT_ID in POINTER_RE.findall(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no paragraph ties `task_type` to the floor and later with "
                f"`see version-matrix: {FACT_ID}`"
            )

        if not any(
            older_sdk_re.search(p)
            and DO_NOT_PASS_RE.search(p)
            and TASK_TYPE_RE.search(p)
            and VALIDATION_ERROR_RE.search(p)
            and EXTRA_FORBIDDEN_RE.search(p)
            and ABSTAIN_RE.search(p)
            for p in paragraphs
        ):
            problems.append(
                f"{rel}: no below-the-floor paragraph saying do not pass `task_type`, "
                "that it raises ValidationError 'Extra inputs are not permitted', "
                "and that the audit abstains"
            )

        flat = " ".join(paragraphs)
        problems.extend(
            f"{rel}: stale universal claim {claim!r}"
            for claim in STALE_CLAIMS
            if claim in flat
        )

    assert not problems, "\n".join(problems)


def _passes_task_type_to_evaluation_options(code: str) -> bool:
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "EvaluationOptions" and any(
            keyword.arg == "task_type" for keyword in node.keywords
        ):
            return True
    return False


def test_task_type_reference_floor_matches_version_matrix(
    repo_root: Path, sync_map: dict
) -> None:
    floor = _floor(repo_root)
    for skill in SKILLS:
        floors = sync_map["skills"][skill].get("python_version_floors") or {}
        assert floors.get(REFERENCE) == floor, (
            f"sync_map.yml {skill}.python_version_floors[{REFERENCE!r}] = "
            f"{floors.get(REFERENCE)!r}; the `{FACT_ID}` matrix row says {floor!r}"
        )
        assert "SKILL.md" not in floors, f"{skill}: SKILL.md must stay unfloored"

        path = repo_root / "skills" / skill / REFERENCE
        assert f"Requires `traigent>={floor}`" in path.read_text(encoding="utf-8"), (
            f"{path.relative_to(repo_root)} must state `Requires `traigent>={floor}``"
        )
        snippets = [
            s
            for s in collect_runnable_file(skill, path)
            if s.language.lower() == "python"
        ]
        assert any(_passes_task_type_to_evaluation_options(s.text) for s in snippets), (
            f"{path.relative_to(repo_root)}: no ```python runnable block calls "
            "EvaluationOptions(..., task_type=...)"
        )


def test_task_type_accepted_iff_installed_sdk_at_or_above_floor(
    repo_root: Path, pytestconfig: pytest.Config
) -> None:
    try:
        from traigent.api.decorators import EvaluationOptions
    except ImportError:
        pytest.skip("traigent.api.decorators.EvaluationOptions is not importable")
    import pydantic

    floor = Version(_floor(repo_root))
    label = _sdk_version_label(pytestconfig)
    installed = Version(importlib.metadata.version("traigent"))
    if label != "develop":
        # Also enforced by test_public_installability; repeated so this module's
        # verdict cannot be about a different SDK than the bucket it reports.
        assert installed == Version(label), (
            f"bucket {label} but traigent {installed} is installed"
        )

    if label == "develop" or installed >= floor:
        options = EvaluationOptions(task_type="exact_match")
        assert options.task_type == "exact_match"
        return

    with pytest.raises(pydantic.ValidationError) as excinfo:
        EvaluationOptions(task_type="exact_match")
    assert any(
        tuple(error["loc"]) == ("task_type",) and error["type"] == "extra_forbidden"
        for error in excinfo.value.errors()
    ), excinfo.value.errors()
