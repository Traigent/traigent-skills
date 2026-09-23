"""optimization-principles.md must agree with preflight and Mode C (#316).

P6 recommended a per-run name (weights, permutation count, date) that
``preflight.md`` uses as its example of what NOT to put in ``experiment_name``,
and P4 said to drop knobs with ~zero impact with no sample floor, which Mode C
forbids below the importance analyzer's floors.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_DIR = Path("skills/traigent-analyze-guidance")
PRINCIPLES = SKILL_DIR / "references" / "optimization-principles.md"
PREFLIGHT = SKILL_DIR / "references" / "preflight.md"
PER_RUN_NAME = re.compile(r"\w+_ACL_80_15_05_txt2sql_216perms_20260620")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n#", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_per_run_name_example_appears_only_as_a_do_not(repo_root: Path) -> None:
    hits = []
    for path in sorted((repo_root / SKILL_DIR).rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in PER_RUN_NAME.finditer(text):
            hits.append((path.relative_to(repo_root).as_posix(), match.start(), text))
    assert len(hits) == 1, [rel for rel, _, _ in hits]
    rel, offset, text = hits[0]
    assert rel == PREFLIGHT.as_posix()
    paragraph_start = text.rfind("\n\n", 0, offset)
    assert text[paragraph_start:offset].strip().startswith("**Do not**")


def test_p6_scopes_the_label_to_the_run_plan_and_keeps_experiment_name_stable(
    repo_root: Path,
) -> None:
    text = (repo_root / PRINCIPLES).read_text(encoding="utf-8")
    p6 = _flat(_section(text, "### P6"))
    assert "**run-plan record**" in p6
    assert "Do not put that label in `experiment_name`" in p6
    assert '"Run naming"' in p6


def test_p4_names_the_sample_floor_and_links_mode_c(repo_root: Path) -> None:
    text = (repo_root / PRINCIPLES).read_text(encoding="utf-8")
    p4 = _flat(_section(text, "### P4"))
    assert "Drop knobs with ~zero impact" not in p4
    assert "at least about 20 completed trials" in p4
    assert "not yet measured" in p4
    assert "Mode C" in p4
    assert "traigent-analyze-variable-importance" in p4
