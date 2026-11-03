"""Issue #470: the ci-safety-gate skill must not teach the deprecated TRAIGENT_MOCK_LLM.

The SDK warns on ``TRAIGENT_MOCK_LLM`` and says it will be removed. The skill taught it as
the zero-spend mechanism for CI. The supported routes are a stub (the reference script's
``--mode mock``) or ``traigent.testing.enable_mock_mode_for_quickstart()`` in the holdout
script. Any surviving mention must be labelled deprecated.
"""

from __future__ import annotations

import re
from pathlib import Path

GATE = "skills/traigent-ci-safety-gate"


def _files(root: Path) -> list[Path]:
    base = root / GATE
    return [base / "SKILL.md", *sorted((base / "references").glob("*.md"))]


def test_every_mock_llm_mention_is_labelled_deprecated(repo_root: Path) -> None:
    offenders = []
    for path in _files(repo_root):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"TRAIGENT_MOCK_LLM", text):
            window = text[max(0, match.start() - 200) : match.end() + 200].lower()
            if "deprecated" not in window:
                offenders.append(f"{path.relative_to(repo_root)}@{match.start()}")
    assert not offenders, offenders


def test_supported_mechanism_is_named(repo_root: Path) -> None:
    skill = " ".join((repo_root / GATE / "SKILL.md").read_text(encoding="utf-8").split())
    assert "enable_mock_mode_for_quickstart()" in skill
    assert "--mode mock" in skill
    ref = (repo_root / GATE / "references/gate-workflow.md").read_text(encoding="utf-8")
    assert "enable_mock_mode_for_quickstart()" in ref
    assert "--mode mock" in ref
