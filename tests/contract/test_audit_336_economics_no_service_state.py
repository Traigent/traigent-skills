"""One consistent instruction for the no-service-result economics state (#336).

Until the Traigent service returns an economics result, the shared economics reference and
the SKILL.md pointers must agree: present the options and the approval ask with no budget
figure of the agent's own (the run's spend cap and dry-run cost estimate are still stated),
say the service sizes the budget, and never present `$0` as the default recommendation. The
reference must also carry no agent-authored budget or spend figure, because an agent copies a
worked example's numbers. Value figures ("a 1-point gain is worth ~$1.5k/day") stay allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

CANONICAL_RELPATH = "docs/shared/economics-characterization.v0.md"

_DOLLARS = r"\$\s*\d[\d,.]*\s*[kKmM]?`?"
_SPEND_WORD = r"(?:budget|spend|spending|test|cap)"

# An agent-authored budget or spend figure. A dollar amount is a budget figure when a spend
# word names it: "`$5`/day test", "$5 a day budget", "$5 daily budget", "a daily budget of
# `$5`", "spend $20 per day". A dollar amount that states value ("worth ~`$1.5k`/day") is not.
BUDGET_FIGURE_PATTERNS = (
    # amount per day, immediately followed by a spend word: "`$5`/day test"
    rf"{_DOLLARS}\s*(?:/|per|a)\s*day\b\W{{0,3}}{_SPEND_WORD}\b",
    # amount, then "daily" and a spend word: "$5 daily budget"
    rf"{_DOLLARS}\s*daily\s+{_SPEND_WORD}\b",
    # a spend word followed, in the same clause, by an amount: "a daily budget of `$5`"
    rf"\b{_SPEND_WORD}\b[^.$—;:]{{0,25}}`?{_DOLLARS}",
)

NO_SERVICE_PARAGRAPH_START = "**Until the backend economics calculator ships"
ALLOWED_ZERO_CLAUSE = (
    "do not present `$0` as the recommendation unless the service returns `$0`"
)


def _canonical_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / CANONICAL_RELPATH).read_text(encoding="utf-8")


def _unwrapped(text: str) -> str:
    """Join wrapped prose lines (and blockquote markers) so sentences match whole."""
    return re.sub(r"\s*\n>?\s*", " ", text)


def _no_service_paragraph(text: str) -> str:
    assert NO_SERVICE_PARAGRAPH_START in text, (
        f"{CANONICAL_RELPATH} lost its no-service-result paragraph"
    )
    start = text.index(NO_SERVICE_PARAGRAPH_START)
    return _unwrapped(text[start:].split("\n\n", 1)[0])


def budget_figures(text: str) -> list[str]:
    unwrapped = _unwrapped(text)
    return [
        m.group(0)
        for pattern in BUDGET_FIGURE_PATTERNS
        for m in re.finditer(pattern, unwrapped, flags=re.IGNORECASE)
    ]


def test_budget_figure_lint_separates_budget_from_value() -> None:
    """The lint catches spend figures in every common shape and leaves value figures alone."""
    for budget in (
        "which is why a `$5`/day test is worth running",
        "which is why a daily budget of `$5` is worth running",
        "propose a $20 per day budget",
        "start with a $5 a day test",
        "a $5 daily budget is enough",
        "spend $50 on the first run",
    ):
        assert budget_figures(budget), f"lint missed a budget figure: {budget!r}"
    for value in (
        "a 1-point accuracy gain is worth ~`$1.5k`/day — which is why a small, capped test",
        "At even `$50` per escalation",
        "customer escalation/rework costing `$50–5,000`",
        "the service recommends `$0`, and you say so",
    ):
        assert not budget_figures(value), f"lint flagged a value figure: {value!r}"


def test_reference_carries_no_agent_authored_budget_figure() -> None:
    hits = budget_figures(_canonical_text())
    assert not hits, (
        f"{CANONICAL_RELPATH} carries an agent-authored budget or spend figure {hits}. The "
        "service sizes the budget; a worked example must not model a number the skills "
        "forbid an agent to produce."
    )


def test_no_service_rule_states_the_cap_and_never_defaults_to_zero() -> None:
    paragraph = _no_service_paragraph(_canonical_text())
    for required in (
        "without a budget figure of your own",
        "still state the run's own spend cap and its dry-run cost estimate",
        "the Traigent service will size the budget",
        ALLOWED_ZERO_CLAUSE,
    ):
        assert required in paragraph, (
            f"no-service rule is missing {required!r}: {paragraph!r}"
        )
    # Outside the one allowed clause, the paragraph must not steer toward spending zero.
    rest = paragraph.replace(ALLOWED_ZERO_CLAUSE, "")
    zero = re.findall(
        r"`?\$\s*0\b`?|\bzero\b|\bno[- ]spend\b", rest, flags=re.IGNORECASE
    )
    assert not zero, (
        f"the no-service paragraph steers toward $0 outside the allowed clause {zero}; the "
        "posture and the SKILL.md pointers say 'Do not default to recommending zero spend'"
    )
    assert "a cap," not in paragraph, (
        "the no-service paragraph forbids stating a cap, but every paid run needs one"
    )


def test_posture_leaves_budget_sizing_to_the_service() -> None:
    posture = _unwrapped(
        _canonical_text().split("## 1. Posture", 1)[1].split("###", 1)[0]
    )
    assert "propose a small daily budget" not in posture, (
        "the posture tells the agent to propose a daily budget itself; the service sizes it"
    )
    assert "the Traigent service sizes its daily budget" in posture
