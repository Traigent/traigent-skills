"""analyze-guidance's no-service economics rule must match the shared reference (#336).

With no service economics result, the agent presents the options and the approval ask
with no budget figure of its own, still states the run's spend cap and dry-run cost
estimate, and says the Traigent service sizes the budget. It must not just stop.
"""

from __future__ import annotations

from pathlib import Path

SKILL = Path("skills/traigent-analyze-guidance/SKILL.md")
START = "**When the service returns no economics result:**"


def test_no_service_paragraph_keeps_the_approval_ask_and_spend_cap(
    repo_root: Path,
) -> None:
    text = (repo_root / SKILL).read_text(encoding="utf-8")
    assert START in text
    paragraph = " ".join(text[text.index(START) :].split("\n\n", 1)[0].split())
    assert "and stop, or continue in Mode C" not in paragraph
    for required in (
        "present the options and the approval ask",
        "**no budget number at all**",
        "spend cap",
        "dry-run cost estimate",
        "the Traigent service sizes the budget",
        "do not present `$0` as the recommendation unless the service returns `$0`",
    ):
        assert required in paragraph, required
