"""Every ``TRAIGENT_MOCK_LLM`` mention says it is deprecated (traigent-skills#343).

traigent 0.27.0 emits ``DeprecationWarning: TRAIGENT_MOCK_LLM is deprecated ...
will be removed in a future release`` (hidden by default). Teaching the env var
without saying so builds fixtures on a removal path. Each line that names it must
have the word "deprecated" within ``WINDOW`` lines.

Scope: the setup skills. The other skills that name the env var are fixed
separately; add them to ``SCOPED_SKILLS`` in
``test_audit_349_fenced_blocks.py`` as they land.
"""

from __future__ import annotations

import re
from pathlib import Path

from .test_audit_349_fenced_blocks import scoped_markdown

WINDOW = 3
DEPRECATED_RE = re.compile(r"\bdeprecated\b", re.I)


def _scan(rel: str, text: str) -> list[str]:
    lines = text.splitlines()
    violations = []
    for index, line in enumerate(lines):
        if "TRAIGENT_MOCK_LLM" not in line:
            continue
        nearby = lines[max(0, index - WINDOW) : index + WINDOW + 1]
        if not any(DEPRECATED_RE.search(other) for other in nearby):
            violations.append(
                f"{rel}:{index + 1}: TRAIGENT_MOCK_LLM without 'deprecated' within "
                f"{WINDOW} lines (point to enable_mock_mode_for_quickstart())"
            )
    return violations


def test_mock_llm_env_var_mentions_carry_the_deprecation(repo_root: Path) -> None:
    violations: list[str] = []
    for path in scoped_markdown(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        violations.extend(_scan(rel, path.read_text(encoding="utf-8")))
    assert not violations, "\n".join(violations)


def test_mock_llm_deprecation_lint_has_teeth() -> None:
    assert _scan("bad.md", "a\nexport TRAIGENT_MOCK_LLM=true\nb\n")
    assert not _scan(
        "ok.md", "export TRAIGENT_MOCK_LLM=true\n\n\nThat env var is deprecated.\n"
    )
    far = "export TRAIGENT_MOCK_LLM=true\n" + "x\n" * (WINDOW + 1) + "deprecated\n"
    assert _scan("far.md", far)
