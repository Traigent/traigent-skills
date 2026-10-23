"""Issue #452: one dataset role, one file name, inside a skill.

``traigent-dataset-curate`` told the reader to create ``eval/tuning.jsonl`` and
then handed them three snippets that load ``eval/tune.jsonl``. An agent that
follows the page in order creates one file and points the SDK at another;
``Dataset.from_jsonl`` raises ``Dataset file not found``, and the obvious repair
(creating the second file) produces a second, divergent dataset.

The lint is scoped so it cannot fire on a snippet that invents its own throwaway
dataset: it applies only to a skill whose **prose** already names at least one
``eval/*.jsonl`` file for the reader to create. In such a skill, every dataset
path a code block loads must be one of those named files.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EVAL_PATH_RE = re.compile(r"eval/[A-Za-z0-9_.-]+\.jsonl")
FENCE_RE = re.compile(r"^\s*(?:>\s*)*(?P<ticks>`{3,})")

CURATE = ROOT / "skills" / "traigent-dataset-curate"
# The files dataset-curate's JSONL-format section tells the reader to create.
CURATE_CREATED = {"eval/tuning.jsonl", "eval/holdout.jsonl"}


def split_code_and_prose(text: str) -> tuple[str, str]:
    """Return (code inside fences, everything else)."""
    code: list[str] = []
    prose: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if fence is None and match:
            fence = match.group("ticks")
            prose.append(line)
            continue
        if fence is not None:
            if match and match.group("ticks").startswith(fence):
                fence = None
                prose.append(line)
            else:
                code.append(line)
            continue
        prose.append(line)
    return "\n".join(code), "\n".join(prose)


def _skill_dirs() -> list[Path]:
    return sorted(d for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").is_file())


def _skill_pages(skill_dir: Path) -> list[Path]:
    return [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]


def _code_and_prose_paths(skill_dir: Path) -> tuple[dict[str, Path], set[str]]:
    in_code: dict[str, Path] = {}
    in_prose: set[str] = set()
    for page in _skill_pages(skill_dir):
        code, prose = split_code_and_prose(page.read_text(encoding="utf-8"))
        for found in EVAL_PATH_RE.findall(code):
            in_code.setdefault(found, page)
        in_prose.update(EVAL_PATH_RE.findall(prose))
    return in_code, in_prose


def test_snippets_load_the_dataset_the_skills_prose_names() -> None:
    violations: list[str] = []
    for skill_dir in _skill_dirs():
        in_code, in_prose = _code_and_prose_paths(skill_dir)
        if not in_prose:
            # The skill never names a dataset file for the reader to create, so
            # its snippets own their own example paths.
            continue
        for path, page in sorted(in_code.items()):
            if path not in in_prose:
                violations.append(
                    f"{page.relative_to(ROOT)}: snippet loads {path!r}, but "
                    f"{skill_dir.name}'s prose names "
                    f"{sorted(in_prose)} as the file(s) to create"
                )
    assert not violations, "\n".join(violations)


def test_curate_snippets_load_only_files_the_page_creates() -> None:
    in_code, _prose = _code_and_prose_paths(CURATE)
    assert in_code, "expected dataset-curate snippets to load a dataset"
    unknown = {path: page for path, page in in_code.items() if path not in CURATE_CREATED}
    assert not unknown, (
        "dataset-curate snippets load files the JSONL-format section never creates: "
        + ", ".join(f"{p} ({page.relative_to(ROOT)})" for p, page in sorted(unknown.items()))
    )


def test_the_lint_has_teeth() -> None:
    text = (
        "Create `eval/tuning.jsonl` first.\n"
        "```python\n"
        'Dataset.from_jsonl("eval/tune.jsonl")\n'
        "```\n"
    )
    code, prose = split_code_and_prose(text)
    assert EVAL_PATH_RE.findall(code) == ["eval/tune.jsonl"]
    assert EVAL_PATH_RE.findall(prose) == ["eval/tuning.jsonl"]
    # The shape the lint must reject: a loaded path the prose never names.
    assert set(EVAL_PATH_RE.findall(code)) - set(EVAL_PATH_RE.findall(prose))
