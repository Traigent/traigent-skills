"""Issue #415: the OpenRouter illustration must not be a delisted model id."""

from __future__ import annotations

from pathlib import Path

LITELLM = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "traigent-setup-integrations"
    / "references"
    / "litellm.md"
)


def test_openrouter_row_uses_a_listed_id_and_keeps_the_verify_caveat() -> None:
    text = LITELLM.read_text(encoding="utf-8")
    row = next(r for r in text.splitlines() if r.startswith("| OpenRouter |"))
    assert "openrouter/anthropic/claude-3-haiku" not in row
    assert "`openrouter/anthropic/claude-haiku-4.5`" in row
    assert "**re-verify them**" in text
