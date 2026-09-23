"""One consistent instruction for the no-service-result economics state (#336).

Until the Traigent service returns an economics result, the shared economics reference and
the SKILL.md pointers must agree: present the options and the approval ask with no dollar
figure, say the service sizes the budget, and never present `$0` as the default
recommendation. The reference must also carry no dollars-per-day budget figure of its own,
because an agent copies a worked example's numbers.
"""

from __future__ import annotations

import re
from pathlib import Path

CANONICAL_RELPATH = "docs/shared/economics-characterization.v0.md"

# A dollars-per-day budget figure: "$5/day", "`$5`/day", "$1.5k / day", "$20 per day".
DAILY_BUDGET_FIGURE = re.compile(
    r"\$\s*\d[\d,.]*\s*[kKmM]?`?\s*(?:/|per)\s*day\b", flags=re.IGNORECASE
)

NO_SERVICE_RULE = "when no service result is available"


def _canonical_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / CANONICAL_RELPATH).read_text(encoding="utf-8")


def _unwrapped(text: str) -> str:
    """Join wrapped prose lines (and blockquote markers) so sentences match whole."""
    return re.sub(r"\s*\n>?\s*", " ", text)


def test_reference_carries_no_daily_budget_figure() -> None:
    hits = DAILY_BUDGET_FIGURE.findall(_canonical_text())
    assert not hits, (
        f"{CANONICAL_RELPATH} carries a dollars-per-day budget figure {hits}. The service "
        "sizes the daily budget; a worked example must not model a number the skills forbid "
        "an agent to produce."
    )


def test_no_service_rule_gives_no_dollar_figure_and_no_default_zero() -> None:
    text = _unwrapped(_canonical_text())
    assert NO_SERVICE_RULE in text, (
        f"{CANONICAL_RELPATH} lost its no-service-result rule"
    )
    rule = text[text.index(NO_SERVICE_RULE) :].split(". ", 1)[0]
    assert "present the spend-`$0` case" not in rule, (
        "the no-service rule tells the agent to present $0, which contradicts the posture "
        "and the SKILL.md pointers ('Do not default to recommending zero spend')"
    )
    for required in (
        "without a dollar figure",
        "the Traigent service will size the budget",
        "do not present `$0` as the recommendation unless the service returns `$0`",
    ):
        assert required in rule, f"no-service rule is missing {required!r}: {rule!r}"


def test_posture_leaves_budget_sizing_to_the_service() -> None:
    posture = _unwrapped(
        _canonical_text().split("## 1. Posture", 1)[1].split("###", 1)[0]
    )
    assert "propose a small daily budget" not in posture, (
        "the posture tells the agent to propose a daily budget itself; the service sizes it"
    )
    assert "the Traigent service sizes its daily budget" in posture
