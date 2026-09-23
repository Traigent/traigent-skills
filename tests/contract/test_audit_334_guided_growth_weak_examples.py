"""Issue #334: never pair ``weak_examples`` with ``grow_dataset`` in one guided call.

On the released SDK ``weak_examples`` takes ``(input, expected, actual)`` tuples
and is read only by ``plan_kind="prompt_rewrite"``; the dataset-growth path that
``grow_dataset`` drives ignores it. ``grow_dataset`` also scores rows with
model-written golds in the same call, before any human review. The lint scans
every ``optimize_with_guidance(`` call written anywhere under ``skills/`` (code
blocks and inline spans) and rejects one that passes both keywords, or that
passes example ids to ``weak_examples``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CURATE = REPO_ROOT / "skills" / "traigent-dataset-curate" / "SKILL.md"
CALL = "optimize_with_guidance("


def _calls(text: str) -> list[tuple[int, str]]:
    """Every optimize_with_guidance(...) call with its balanced argument text."""
    calls = []
    start = text.find(CALL)
    while start != -1:
        depth, index = 0, start + len(CALL) - 1
        while index < len(text):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        calls.append((text.count("\n", 0, start) + 1, text[start : index + 1]))
        start = text.find(CALL, start + 1)
    return calls


def test_no_call_pairs_weak_examples_with_grow_dataset() -> None:
    offenders = []
    for path in sorted((REPO_ROOT / "skills").rglob("*.md")):
        for line, call in _calls(path.read_text(encoding="utf-8")):
            where = f"{path.relative_to(REPO_ROOT)}:{line}"
            if "weak_examples=" in call and "grow_dataset=" in call:
                offenders.append(f"{where}: weak_examples= next to grow_dataset=")
            if "weak_examples=" in call and re.search(r"\bids\b|_ids\b", call):
                offenders.append(f"{where}: example ids passed to weak_examples")
    assert not offenders, (
        "weak_examples takes (input, expected, actual) tuples and is read only by "
        'plan_kind="prompt_rewrite"; it never steers grow_dataset:\n'
        + "\n".join(offenders)
    )


def test_guided_growth_snippet_warns_about_review_bypass() -> None:
    text = CURATE.read_text(encoding="utf-8")
    section = text.split("## Synthesize examples client-side", 1)[1].split("\n## ", 1)[
        0
    ]
    assert "in the same call" in section and "before any human review" in section
    assert "across datasets of different sizes" in section
    assert 'plan_kind="prompt_rewrite"' in section
