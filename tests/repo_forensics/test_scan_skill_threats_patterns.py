from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "repo-forensics"))

import scan_skill_threats  # noqa: E402


def _scope_patterns(label: str):
    return [p for p, desc in scan_skill_threats.SCOPE_PATTERNS if desc == label]


def test_home_directory_pattern_matches_literal_dollar_home() -> None:
    patterns = _scope_patterns("Accessing user home directories")
    assert any(p.search("cat $HOME/notes.txt") for p in patterns)


def test_claude_config_pattern_matches_literal_dollar_home() -> None:
    patterns = _scope_patterns("Accessing Claude configuration")
    assert any(p.search("cp x $HOME/.claude/skills/y") for p in patterns)
