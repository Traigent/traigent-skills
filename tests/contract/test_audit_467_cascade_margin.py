"""Issue #467: the cascade gate "margin" is the top-vote share, not a gap.

``margin = top_count / n`` and the gate escalates when ``margin < threshold`` (equality does
not escalate). The skill never said so, so users picked thresholds that cannot fire: a
2-sample base arm at 0.5, or the Quick Start's 0.3 on 3 samples. The test runs the real
cascade for each sample count and threshold and checks the bands the skill states.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL = "skills/traigent-optimize-composite-knobs/SKILL.md"
CATALOG = "skills/traigent-optimize-composite-knobs/references/pattern-catalog.md"


def _flat(root: Path, rel: str) -> str:
    return " ".join((root / rel).read_text(encoding="utf-8").split())


def test_skill_defines_the_margin_and_its_bands(repo_root: Path) -> None:
    text = _flat(repo_root, SKILL)
    assert "top-vote share" in text
    assert "margin = (votes for the most common answer) / (samples)" in text
    assert "`margin < threshold`" in text and "Equality does not escalate" in text
    assert "2-sample" in text and "threshold of 0.5 or lower never escalates" in text
    assert "`0.3` escalates no non-empty vote" in text
    assert "`0.5` escalates only a three-way split" in text
    assert "`0.7` escalates every non-unanimous vote" in text
    assert "GATE: [0.3, 0.5, 0.7]" in text, "the Quick Start grid stays"


def test_pattern_catalog_defines_margin_for_binary_cascade(repo_root: Path) -> None:
    assert "top-vote share" in _flat(repo_root, CATALOG)


def _escalated(outputs: list[str], threshold: float) -> bool:
    from traigent.knobs.patterns import binary_cascade
    from traigent.knobs.runtime import StageRunner, execute_composite

    gate = "gate_threshold"
    composite = binary_cascade("answerer", base_stage="cheap", expert_stage="strong", threshold=gate)

    def stage(vals: list[str]) -> StageRunner:
        return StageRunner(run=lambda _item: list(vals), key_fn=lambda x: x, samples=len(vals))

    run = execute_composite(
        composite.structure,
        {"cheap": stage(outputs), "strong": stage(["EXPERT"])},
        config={gate: threshold},
        calibrated_values={gate: threshold},
    )
    return str(run.output) == "EXPERT"


# (base-arm votes, threshold, escalates?) — the discrete bands the skill states.
BANDS = [
    (["A", "B"], 0.5, False),        # 1-1 split has margin 0.5; 0.5 never fires
    (["A", "B"], 0.51, True),
    (["A", "A", "B"], 0.3, False),   # margin 2/3
    (["A", "A", "B"], 0.5, False),
    (["A", "A", "B"], 0.7, True),
    (["A", "B", "C"], 0.3, False),   # margin 1/3 is not below 0.3
    (["A", "B", "C"], 0.5, True),
    (["A", "A", "A"], 0.7, False),   # unanimous: margin 1.0
]


@pytest.mark.parametrize(("votes", "threshold", "expected"), BANDS)
def test_stated_bands_match_the_sdk(votes: list[str], threshold: float, expected: bool) -> None:
    pytest.importorskip("traigent.knobs.patterns")
    assert _escalated(votes, threshold) is expected


def test_empty_vote_has_margin_zero_as_the_skill_states(repo_root: Path) -> None:
    cascade = pytest.importorskip("traigent.knobs.cascade")
    assert cascade.vote_over([], 3).margin == 0.0
    assert "empty or abstain-only vote has margin 0" in _flat(repo_root, SKILL)
