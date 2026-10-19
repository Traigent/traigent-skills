"""Issue #449: unfixed caveats must not be bounded to an old "latest tested" release.

The mock-synthesis and ``BaseEvaluator`` caveats still hold on traigent 0.30.0, so a
``<= 0.27.0`` bound reads as "fixed in 0.28.0+" and misleads readers on newer releases.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
SITES = [
    SKILLS / "traigent-dataset-curate" / "SKILL.md",
    SKILLS / "traigent-eval-build" / "SKILL.md",
    SKILLS / "traigent-boost-agent" / "SKILL.md",
]
CAVEAT = re.compile(r"Mock mode does not cover|wireable|accepts one", re.IGNORECASE)


def test_unfixed_caveats_have_no_old_upper_bound() -> None:
    offenders = []
    for path in SITES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CAVEAT.search(line) and re.search(r"<=\s*0\.27\.0", line):
                offenders.append(f"{path.parent.name}/SKILL.md:{number}")
    assert not offenders, f"stale '<= 0.27.0' bound on an unfixed caveat: {offenders}"


def test_caveats_name_the_checked_range() -> None:
    for path in SITES:
        text = path.read_text(encoding="utf-8")
        assert "through 0.30.0" in text, f"{path.parent.name}: caveat lost its checked range"
