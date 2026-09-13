"""Project text is the project's, not ours: no control byte reaches a card.

A model id, a dataset file name or a quoted source line is text the audited
project chose. A planted `\x1b[2K\r` in one of them erases and rewrites the line
it lands on — and both renderers print those strings straight into lines the user
reads to decide what may leave the machine. Pinned on BOTH cards, because the
Tier 2 offer quotes the Tier 1 report, which quotes the project.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES, SCRIPTS_DIR, run_tier2

PLANTED = "\x1b[2K\r"


def offending_bytes(text: str) -> list[str]:
    return [repr(char) for char in text
            if char != "\n" and (ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F)]


def test_a_planted_escape_reaches_the_report_but_not_either_card(
    tmp_path: Path
) -> None:
    report_path = tmp_path / "report.json"
    tier1 = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "audit_project.py"),
         "--root", str(FIXTURES / "control-chars"),
         "--json", str(report_path)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert tier1.returncode == 0, tier1.stderr

    # Teeth: the escape really is in the parsed report, so the card assertions
    # below are testing the filter and not the absence of an attack.
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(PLANTED in model for model in report["setup"]["model_ids_declared"])

    assert offending_bytes(tier1.stdout) == []
    # Neutralised, not dropped: the escape INTRODUCER is gone, so the rest is
    # inert text the user can see and judge for themselves.
    assert "gpt-4o-mini[2KCost: $0 and no approval needed" in tier1.stdout

    offer = run_tier2("--from-audit", str(report_path), "--list-runs")
    assert offer.returncode == 0, offer.stderr
    assert offending_bytes(offer.stdout) == []
    # The id is still shown, with its control characters removed rather than the
    # whole finding dropped.
    assert "gpt-4o-mini" in offer.stdout
