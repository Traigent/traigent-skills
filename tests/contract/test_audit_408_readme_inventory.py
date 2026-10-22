"""Issue #408: README policy summary and script inventory must match the source tree."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())


def test_recommendation_summary_matches_the_gated_policy() -> None:
    assert "always recommends the next Traigent skill" not in README
    assert "never during setup or mid-walkthrough" in README
    assert "at most three per response" in README


def test_every_script_bearing_skill_is_in_the_readme_inventory() -> None:
    script_skills = sorted(
        path.parent.parent.name
        for path in (ROOT / "skills").glob("*/scripts/*.py")
    )
    assert script_skills
    for name in set(script_skills):
        assert f"`{name}`" in README, f"README omits script-bearing skill {name}"
    assert "These skills are Markdown, with two exceptions" not in README
