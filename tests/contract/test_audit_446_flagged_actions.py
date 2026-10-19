"""Issue #446: flagged-example docs must not teach the retired ``remove_redundant``.

The SDK rejects ``remove_redundant`` fail-closed (subtractive pruning keyed to an
observed signal biases the customer's own measurement). The docs' enum row must
be a subset of the SDK allowlist, and no table may prescribe deleting rows from
a server flag.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CURATE = ROOT / "skills" / "traigent-dataset-curate" / "SKILL.md"
INSIGHTS = ROOT / "skills" / "traigent-boost-agent" / "references" / "insights-and-iteration.md"


def test_retired_action_is_not_taught() -> None:
    for path in ROOT.glob("skills/**/*.md"):
        assert "remove_redundant" not in path.read_text(encoding="utf-8").replace(
            "the SDK retired `remove_redundant` for this reason", ""
        ), path


def test_redundant_pattern_does_not_prescribe_deletion() -> None:
    for path in (CURATE, INSIGHTS):
        rows = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("| `redundant_pattern`")
        ]
        assert rows, path
        for row in rows:
            assert "Remove or dedupe" not in row
            assert "Do not delete rows" in row


def test_flagged_protocol_names_example_insights_not_dataset_quality() -> None:
    text = CURATE.read_text(encoding="utf-8")
    boundary = text.split("### Boundary", 1)[1].split("### Protocol", 1)[0]
    protocol = text.split("### Protocol", 1)[1][:600]
    assert "analytics_get_example_insights" in boundary
    assert "analytics_get_example_insights" in protocol
    assert "from the example-scoring\n  dataset-quality" not in boundary


def test_documented_actions_are_in_sdk_allowlist() -> None:
    analytics_client = pytest.importorskip("traigent.cloud.analytics_client")
    allowed = analytics_client._EXAMPLE_INSIGHT_RECOMMENDED_ACTIONS
    row = next(
        line
        for line in CURATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `recommended_action`")
    )
    documented = set(re.findall(r"[a-z_]+", re.split(r"(?<!\\)\|", row)[2].replace("\\", " ")))
    assert documented <= set(allowed), documented - set(allowed)
