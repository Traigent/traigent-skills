"""Issue #428: the portal run link template is /experiments/view/<experiment_id>?run_id=..."""

from __future__ import annotations

from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
GOOD = "https://portal.traigent.ai/experiments/view/<experiment_id>?run_id=<run_id>"


def test_no_dead_portal_link_template() -> None:
    offenders = [
        str(p.relative_to(SKILLS))
        for p in SKILLS.rglob("*.md")
        if "portal.traigent.ai/p/" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_sites_use_the_working_route_and_prefer_cloud_url() -> None:
    for rel in (
        "traigent-analyze-guidance/SKILL.md",
        "traigent-analyze-results/SKILL.md",
        "traigent-analyze-results/references/mcp-analytics-tools.md",
    ):
        text = (SKILLS / rel).read_text(encoding="utf-8")
        assert GOOD in text, rel
        assert "cloud_url" in text, rel
