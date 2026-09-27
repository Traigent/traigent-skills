"""Boost-agent: naming the analytics MCP tool must come with its setup pointer.

Traigent/traigent-skills#314 (the boost-agent sibling). The insights reference
names the ``analytics_get_example_insights`` MCP tool, but the tool exists only
after the analytics MCP server is installed and registered, and the page never
said so or pointed at the setup steps.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "skills" / "traigent-boost-agent" / "references" / "insights-and-iteration.md"
TOOL = "analytics_get_example_insights"
POINTER = '"Prerequisites (one time)"'


def test_mcp_tool_mention_carries_the_setup_pointer() -> None:
    lines = REFERENCE.read_text(encoding="utf-8").splitlines()
    mentions = [index for index, line in enumerate(lines) if TOOL in line]
    assert mentions, f"{REFERENCE.name} no longer names {TOOL}; drop this test"
    first = mentions[0]
    paragraph = []
    for line in lines[first:]:
        if not line.strip():
            break
        paragraph.append(line)
    text = " ".join(paragraph)
    assert POINTER in text and "analyze-results skill" in text, (
        f"{REFERENCE.name}:{first + 1}: first mention of {TOOL} has no install/registration "
        "pointer to the analyze-results skill's \"Prerequisites (one time)\""
    )
    assert "REST route works without it" in text, text
