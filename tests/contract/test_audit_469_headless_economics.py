"""Issue #469: define the stop path when required economics answers cannot be confirmed.

In a headless/CI session nobody can answer Q1, Q3 or the Q2 forecast. The reference must
give an explicit ``pending_user_confirmation`` state with the allowed values, say to stop
before budget sizing and any paid run, forbid inference and an invalid partial draft, and
keep the interactive flow. The nine generated copies must stay in sync (sync tool --check).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CANONICAL = "docs/shared/economics-characterization.v0.md"


def _section(root: Path) -> str:
    text = (root / CANONICAL).read_text(encoding="utf-8")
    start = text.index("### When no user can answer")
    return " ".join(text[start:].split("\n## ", 1)[0].split())


def test_headless_stop_path_is_defined(repo_root: Path) -> None:
    s = _section(repo_root)
    for required in (
        "`value_channel`",
        "`error_cost_band`",
        "forecast",
        "`pending_user_confirmation`",
        "allowed closed values",
        "Stop before budget sizing and before launching any paid run",
        "Do not infer, default, or carry over",
        "Do not write an incomplete survey draft",
        "Resume",
        "an interactive session keeps the flow above unchanged",
    ):
        assert required.lower() in s.lower(), f"headless section lost {required!r}"
    # every closed Q1 value is listed in the worked pending line, so the report is actionable
    for value in (
        "save_expert_time", "replace_manual_operations", "process_volume_cheaper",
        "increase_revenue", "prevent_costly_mistakes",
    ):
        assert value in s


def test_recording_section_blocks_a_draft_while_pending(repo_root: Path) -> None:
    text = " ".join((repo_root / CANONICAL).read_text(encoding="utf-8").split())
    assert "While Q1, Q3, or the Q2 forecast is `pending_user_confirmation`" in text
    assert "write no draft at all" in text


def test_generated_copies_are_synchronized(repo_root: Path) -> None:
    done = subprocess.run(
        [sys.executable, "tools/contract/sync_economics_reference.py", "--check"],
        cwd=repo_root, text=True, capture_output=True, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
