"""preflight.md must not contradict itself about named smart selectors (#190).

"Algorithm prerequisites" says named smart selectors execute on authenticated
connected runs since 0.20.1; the "Execution selector" section used to say they
do not currently run as selector names.
"""

from __future__ import annotations

from pathlib import Path

PREFLIGHT = Path("skills/traigent-analyze-guidance/references/preflight.md")


def test_execution_selector_section_agrees_with_algorithm_prerequisites(
    repo_root: Path,
) -> None:
    text = " ".join((repo_root / PREFLIGHT).read_text(encoding="utf-8").split())
    prerequisites = text.split("## Algorithm prerequisites", 1)[1].split("## ", 1)[0]
    selector = text.split("## Execution selector and portal tracking", 1)[1].split(
        "## ", 1
    )[0]
    assert "execute on connected runs since 0.20.1" in prerequisites
    assert "do **not** currently run as selector names" not in selector
    assert "run only on authenticated connected runs" in selector
    assert "never with `offline=True`" in selector
