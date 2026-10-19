"""Issue #416: the shared policy tells agents how to answer 'which Skills did you use?'."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_policy_has_request_driven_skill_usage_clause_in_every_skill() -> None:
    clause = "When the user asks which Skills were used"
    for path in [ROOT / "docs" / "shared" / "interaction-policy.v1.md", *sorted((ROOT / "skills").glob("*/SKILL.md"))]:
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert text.count(clause) == 1, path
        assert "never infer absence from non-use" in text, path
        assert "Do not volunteer this unasked" in text, path
