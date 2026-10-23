"""Issue #409: process liveness must not be presented as proof that the editor opened."""

from __future__ import annotations

from pathlib import Path

SKILL = (
    Path(__file__).resolve().parents[2] / "skills" / "traigent-setup-quickstart" / "SKILL.md"
)


def test_skill_treats_process_checks_as_advisory_and_keeps_the_fallback() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "Verify the editor process is actually alive" not in text
    assert "advisory only" in text
    assert "matches the invoking shell" in text
    assert "Ask the user to confirm the intended window appeared" in text
    assert "fall back to the printed absolute path" in text

