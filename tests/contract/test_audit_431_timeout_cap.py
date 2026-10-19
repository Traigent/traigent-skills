"""Issue #431: timeout advice must disclose the per-example cap and not suggest timeout=30."""

from __future__ import annotations

from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
DEBUGGING = SKILLS / "traigent-debugging" / "SKILL.md"
RUN = SKILLS / "traigent-optimize-run" / "SKILL.md"
SPINE = SKILLS / "traigent-optimize-config-space" / "references" / "structural-spine.md"
CAP = "capped at this value, or 60 s when unset"


def test_debugging_and_run_disclose_per_example_cap() -> None:
    for page in (DEBUGGING, RUN):
        assert CAP in page.read_text(encoding="utf-8"), page


def test_debugging_does_not_suggest_timeout_30() -> None:
    assert "timeout=30" not in DEBUGGING.read_text(encoding="utf-8")


def test_spine_does_not_promise_long_per_request_timeouts_work() -> None:
    text = SPINE.read_text(encoding="utf-8")
    assert "Keep a per-request timeout inside your own LLM call instead." not in text
    assert "capped at 60 s" in text
