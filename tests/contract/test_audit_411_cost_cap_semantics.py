"""Issue #411: the run-cost card must not present cost_limit as a hard guarantee."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "docs" / "shared" / "run-cost-and-limits.v1.md"
RUN = ROOT / "skills" / "traigent-optimize-run" / "SKILL.md"


def test_card_names_trial_granular_overshoot_and_the_prompt() -> None:
    text = " ".join(CARD.read_text(encoding="utf-8").split())
    assert "not a hard billing ceiling" in text
    assert "one trial at a time" in text and "in flight" in text
    assert "interactive terminal" in text and "approve" in text
    assert "advisory" in text and "provider can actually enforce" in text


def test_optimize_run_mirrors_the_semantics() -> None:
    text = " ".join(RUN.read_text(encoding="utf-8").split())
    assert "one trial at a time" in text and "overshoot" in text
    assert "not a provider-side hard billing ceiling" in text
