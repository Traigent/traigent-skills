"""Issue #362: the shared interaction-policy snippet must compile and fail soft as a script."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "docs" / "shared" / "interaction-policy.v1.md"


def _snippet(path: Path) -> str:
    match = re.search(r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, path
    return match.group(1)


def test_snippet_compiles_as_a_script() -> None:
    compile(_snippet(POLICY), "<policy>", "exec")


def test_snippet_without_a_client_leaves_policy_none() -> None:
    namespace: dict[str, object] = {}
    exec(compile(_snippet(POLICY), "<policy>", "exec"), namespace)  # noqa: S102 - repo-owned doc snippet
    assert namespace["policy"] is None


def test_every_skill_carries_the_compiling_snippet() -> None:
    expected = _snippet(POLICY)
    skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
    assert skills
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        assert text.count("## Traigent Interaction Policy") == 1, skill
        assert expected in text, skill
